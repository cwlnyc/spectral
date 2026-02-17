#!/usr/bin/env python3
"""
Shopify to Amazon PAINT Template Converter - Factory Packs with Variations

Converts Shopify product export CSV files to Amazon's tab-delimited
upload format with parent/child variation structure for factory pack paints.
"""

import csv
import argparse
import json
from pathlib import Path
from html import unescape
import re
from collections import defaultdict

# Path to template headers JSON (extracted from PAINT.xlsm)
TEMPLATE_HEADERS_FILE = Path(__file__).parent / 'amazon_template_headers.json'
FACTORY_PACK_DESC_FILE = Path(__file__).parent / 'factory_pack_description.txt'

# Related product ASINs for cross-references
RELATED_PRODUCTS = {
    'clear_coat_kit': 'B0GCGHRP86',  # 2K 4:1 Clear Coat Kit
}


def load_template_headers():
    """Load the Amazon template headers from JSON file."""
    with open(TEMPLATE_HEADERS_FILE, 'r') as f:
        return json.load(f)


def load_factory_pack_description():
    """Load the standard factory pack description."""
    if FACTORY_PACK_DESC_FILE.exists():
        with open(FACTORY_PACK_DESC_FILE, 'r') as f:
            text = f.read().strip()
            # Replace newlines with spaces for Amazon compatibility
            text = ' '.join(text.split())
            return text
    return ''


def strip_html(html_text):
    """Remove HTML tags and decode entities."""
    if not html_text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = unescape(text)
    text = ' '.join(text.split())
    return text.strip()


def read_shopify_csv(filepath):
    """Read Shopify CSV and group variants by parent title (not handle, as handles can be duplicated)."""
    product_families = defaultdict(list)

    for encoding in ['utf-8-sig', 'utf-8', 'cp1252', 'latin-1']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode {filepath} with any known encoding")

    parent_title = ''
    parent_body = ''
    parent_handle = ''
    parent_color_code = ''
    parent_make = ''

    for row in rows:
        if row.get('Title', '').strip():
            parent_title = row.get('Title', '')
            parent_body = row.get('Body (HTML)', '')
            parent_handle = row.get('Handle', '')
            parent_color_code = row.get('color code (product.metafields.custom.color_code)', '')
            parent_make = row.get('make (product.metafields.custom.make)', '')

        sku = row.get('Variant SKU', '').strip()
        if not sku:
            continue

        product = dict(row)
        product['Variant SKU'] = sku
        product['parent_title'] = parent_title
        product['parent_body'] = parent_body
        product['parent_handle'] = parent_handle
        product['parent_color_code'] = parent_color_code
        product['parent_make'] = parent_make

        # Group by title instead of handle to handle cases where
        # different products share the same Shopify handle
        product_families[parent_title].append(product)

    return product_families


def create_parent_sku(handle, color_code=''):
    """Generate a unique parent SKU from the handle and color code."""
    # Use color code if available, otherwise extract key part from handle
    if color_code:
        return f"SP-PARENT-{color_code.upper().replace(' ', '').replace('/', '-')}"
    # Extract meaningful part from handle
    clean = handle.replace('for-', '').replace('-gallon-paint', '').replace('-paint', '')
    # Take first 25 chars to keep it reasonable
    return f"SP-PARENT-{clean[:25].upper().replace('-', '')}"


def extract_color_code_from_title(title):
    """Extract color code from title if not in metafield."""
    import re
    # Look for patterns like WA8624, PW7, 040, 1F7, etc.
    patterns = [
        r'\b(WA\d+)\b',  # WA8624, WA636R, etc.
        r'\b([A-Z]{2}\d+)\b',  # PW7, PX8, UA, UH, RR, etc.
        r'\b(\d{3})\b',  # 040
        r'\b(\d[A-Z]\d)\b',  # 1F7
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ''


def map_parent_to_amazon(family_products, column_names, factory_description):
    """Create a parent row for a product family."""
    amazon_row = {col: '' for col in column_names}

    # Use first child's data for parent info
    first_child = family_products[0]
    title = first_child.get('parent_title', '') or first_child.get('Title', '')
    color_code = first_child.get('parent_color_code', '')
    make = first_child.get('parent_make', '')

    # If no color code in metafield, try to extract from title
    if not color_code:
        color_code = extract_color_code_from_title(title)

    # Parent SKU - use color code if available for uniqueness
    parent_sku = create_parent_sku(first_child['parent_handle'], color_code)

    # Listing Identity
    amazon_row['SKU'] = parent_sku
    amazon_row['Listing Action'] = 'Create or Replace (Full Update)'

    # Product Identity - Parent has minimal info
    amazon_row['Product Type'] = 'PAINT'
    amazon_row['Item Name'] = title[:500]
    amazon_row['Brand Name'] = 'Spectral Paints'
    amazon_row['Product Id Type'] = 'GTIN Exempt'  # Parent doesn't need UPC
    amazon_row['Item Type Keyword'] = 'automotive-paints'
    amazon_row['Manufacturer'] = 'Spectral Paints'

    # Variation - Parent settings
    amazon_row['Parentage Level'] = 'Parent'
    amazon_row['Parent SKU'] = ''  # Parent doesn't have a parent
    amazon_row['Variation Theme Name'] = 'COLOR/SIZE'

    # Product Details
    amazon_row['Product Description'] = factory_description[:2000]
    amazon_row['Color'] = color_code if color_code else 'Custom'
    amazon_row['Color Code'] = color_code if color_code else ''

    # Product Details for parent
    amazon_row['Coverage'] = '150-200 Square Feet'
    amazon_row['Surface Recommendation'] = 'Metal'

    # Safety & Compliance
    amazon_row['Country of Origin'] = 'United States'
    amazon_row['Are batteries required?'] = 'No'
    amazon_row['Are batteries included?'] = 'No'
    amazon_row['Safety Data Sheet (SDS or MSDS) URL'] = 'spectralpaints.biz'

    # Get main image from first variant
    main_image = first_child.get('Variant Image', '') or first_child.get('Image Src', '')
    amazon_row['Main Image URL'] = main_image

    # Create bullet points from factory description
    bullets = create_bullet_points(factory_description, make, color_code)

    return amazon_row, bullets, parent_sku


def map_child_to_amazon(shopify_product, column_names, parent_sku, factory_description):
    """Map a Shopify product variant to Amazon child row."""
    amazon_row = {col: '' for col in column_names}

    title = shopify_product.get('parent_title', '') or shopify_product.get('Title', '')
    option_value = shopify_product.get('Option1 Value', '').strip()
    color_code = shopify_product.get('parent_color_code', '')
    make = shopify_product.get('parent_make', '')

    # If no color code in metafield, try to extract from title
    if not color_code:
        color_code = extract_color_code_from_title(title)

    # Build item name with size
    if option_value:
        item_name = f"{title} - {option_value}"
    else:
        item_name = title

    # Get UPC if available
    upc = shopify_product.get('UPC (product.metafields.facts.upc)', '').strip()

    # Get image
    main_image = shopify_product.get('Variant Image', '') or shopify_product.get('Image Src', '')

    # Listing Identity
    amazon_row['SKU'] = shopify_product.get('Variant SKU', '')
    amazon_row['Listing Action'] = 'Create or Replace (Full Update)'

    # Product Identity
    amazon_row['Product Type'] = 'PAINT'
    amazon_row['Item Name'] = item_name[:500]
    amazon_row['Brand Name'] = 'Spectral Paints'
    amazon_row['Product Id Type'] = 'UPC' if upc else 'GTIN Exempt'
    amazon_row['Product Id'] = upc
    amazon_row['Item Type Keyword'] = 'automotive-paints'
    amazon_row['Manufacturer'] = 'Spectral Paints'

    # Variation - Child settings
    amazon_row['Parentage Level'] = 'Child'
    amazon_row['Parent SKU'] = parent_sku
    amazon_row['Variation Theme Name'] = 'COLOR/SIZE'

    # Offer
    amazon_row['Item Condition'] = 'New'
    price = shopify_product.get('Variant Price', '')
    amazon_row['List Price'] = price
    amazon_row['Your Price USD (Sell on Amazon, US)'] = price

    # Offer (US)
    amazon_row['Fulfillment Channel Code (US)'] = 'DEFAULT'
    amazon_row['Quantity (US)'] = '30'
    amazon_row['Handling Time (US)'] = '2'
    amazon_row['Merchant Shipping Group (US)'] = 'Migrated Template'

    # Product Details
    amazon_row['Product Description'] = factory_description[:2000]
    amazon_row['Number of Items'] = '1'
    amazon_row['Color'] = color_code if color_code else 'Custom'
    amazon_row['Color Code'] = color_code if color_code else ''
    amazon_row['Part Number'] = shopify_product.get('Variant SKU', '')
    amazon_row['Surface Recommendation'] = 'Metal'
    amazon_row['Coverage'] = '150-200 Square Feet'
    amazon_row['Paint Type'] = 'Urethane'
    amazon_row['Finish Type'] = 'Metallic'
    amazon_row['Item Form'] = 'Liquid'
    amazon_row['Specific Uses for Product'] = 'Exterior'

    # Volume, Size, and Unit Count based on option value
    size_lower = option_value.lower() if option_value else ''
    if 'gallon' in size_lower:
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Gallons'
        amazon_row['Size'] = '1 Gallon'
        amazon_row['Unit Count'] = '128'
        amazon_row['Unit Count Type'] = 'Fl Oz'
    elif 'quart' in size_lower:
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Quarts'
        amazon_row['Size'] = '1 Quart'
        amazon_row['Unit Count'] = '32'
        amazon_row['Unit Count Type'] = 'Fl Oz'
    elif 'pint' in size_lower:
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Pints'
        amazon_row['Size'] = '1 Pint'
        amazon_row['Unit Count'] = '16'
        amazon_row['Unit Count Type'] = 'Fl Oz'
    else:
        amazon_row['Unit Count'] = '1'
        amazon_row['Unit Count Type'] = 'Count'

    # Safety & Compliance
    amazon_row['Country of Origin'] = 'United States'
    amazon_row['Are batteries required?'] = 'No'
    amazon_row['Are batteries included?'] = 'No'
    amazon_row['Safety Data Sheet (SDS or MSDS) URL'] = 'spectralpaints.biz'

    # Images
    amazon_row['Main Image URL'] = main_image

    # Create bullet points
    bullets = create_bullet_points(factory_description, make, color_code)

    return amazon_row, bullets


def create_bullet_points(factory_description, make='', color_code=''):
    """Create bullet points from factory description."""
    bullets = []

    # Split description into bullet points
    lines = factory_description.split('\n\n')

    # First bullet: color code
    if color_code:
        bullets.append(f"Color Code: {color_code}")
    else:
        bullets.append("1K urethane base coat paint. Easy to spray.")

    # Second bullet: clear coat requirement
    bullets.append("Finishing with clear coat is required. We recommend our 2K 4:1 Clear Coat Kit for professional results.")

    # Third bullet: surface prep
    bullets.append("Surface must be primed or previously painted and sufficiently prepped before applying basecoat. Use Adhesion Promoter on raw plastic.")

    # Fourth bullet: mixing instructions
    bullets.append("Product comes UNREDUCED. Mix 1:1 with Urethane Reducer for approximately 2 quarts of sprayable product (150-200 sq ft coverage).")

    # Fifth bullet: brand info
    bullets.append("Spectral Paints is a Registered Brand of Spectral Paints LLC. All products are final sale - please verify color match before starting.")

    # Pad to 5 bullets - use space to force Amazon to overwrite old values
    while len(bullets) < 5:
        bullets.append(' ')

    return bullets[:5]


def write_amazon_txt(products, bullets_list, output_path, template_headers):
    """Write products to Amazon tab-delimited format with proper headers."""
    settings = template_headers['settings']
    instructions = template_headers['instructions']
    categories = template_headers['categories']
    columns = template_headers['columns']
    attributes = template_headers['attributes']
    num_cols = len(columns)

    # Pad header rows
    for header_list in [settings, instructions, categories, attributes]:
        while len(header_list) < num_cols:
            header_list.append('')

    with open(output_path, 'w', encoding='cp1252', newline='') as f:
        f.write('\t'.join(settings[:num_cols]) + '\r\n')
        f.write('\t'.join(instructions[:num_cols]) + '\r\n')
        f.write('\t'.join(categories[:num_cols]) + '\r\n')
        f.write('\t'.join(columns[:num_cols]) + '\r\n')
        f.write('\t'.join(attributes[:num_cols]) + '\r\n')

        writer = csv.writer(f, delimiter='\t', lineterminator='\r\n')

        for product, bullets in zip(products, bullets_list):
            row = []
            bullet_idx = 0
            ghs_idx = 0
            dg_idx = 0

            for i, col_name in enumerate(columns):
                if col_name == 'Bullet Point':
                    if bullet_idx < len(bullets):
                        row.append(bullets[bullet_idx][:500] if bullets[bullet_idx] else '')
                    else:
                        row.append('')
                    bullet_idx += 1
                elif col_name == 'Dangerous Goods Regulations':
                    if dg_idx == 0:
                        row.append('Other')
                    elif dg_idx <= 4:
                        row.append('GHS')
                    else:
                        row.append('')
                    dg_idx += 1
                elif col_name == 'GHS Class':
                    if ghs_idx == 0:
                        row.append('Amazon Specific No Label With Warning')
                    elif ghs_idx == 1:
                        row.append('Irritant')
                    else:
                        row.append('')
                    ghs_idx += 1
                elif col_name in product:
                    row.append(product[col_name])
                else:
                    row.append('')

            while len(row) < num_cols:
                row.append('')
            writer.writerow(row[:num_cols])

    return len(products)


def main():
    parser = argparse.ArgumentParser(
        description='Convert Shopify CSV to Amazon PAINT template with parent/child variations'
    )
    parser.add_argument('input_csv', help='Path to Shopify CSV export file')
    parser.add_argument('-o', '--output', help='Output .txt file path')

    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return 1

    output_path = args.output or input_path.stem + '_amazon.txt'

    # Load template headers
    print("Loading Amazon template headers...")
    template_headers = load_template_headers()
    columns = template_headers['columns']
    print(f"Template has {len(columns)} columns")

    # Load factory pack description
    print("Loading factory pack description...")
    factory_description = load_factory_pack_description()
    if factory_description:
        print(f"Loaded description ({len(factory_description)} chars)")
    else:
        print("Warning: No factory pack description found")

    print(f"Reading Shopify CSV: {input_path}")
    product_families = read_shopify_csv(input_path)
    print(f"Found {len(product_families)} product families")

    print("Mapping to Amazon format with parent/child variations...")
    amazon_products = []
    bullets_list = []

    for handle, variants in product_families.items():
        # Create parent row
        parent_row, parent_bullets, parent_sku = map_parent_to_amazon(
            variants, columns, factory_description
        )
        amazon_products.append(parent_row)
        bullets_list.append(parent_bullets)

        # Create child rows
        for variant in variants:
            child_row, child_bullets = map_child_to_amazon(
                variant, columns, parent_sku, factory_description
            )
            amazon_products.append(child_row)
            bullets_list.append(child_bullets)

    print(f"Writing to: {output_path}")
    count = write_amazon_txt(amazon_products, bullets_list, output_path, template_headers)

    # Count parents and children
    parent_count = len(product_families)
    child_count = count - parent_count

    print(f"Done! Wrote {count} rows ({parent_count} parents + {child_count} children)")
    print(f"File includes 5 header rows + {count} data rows")
    return 0


if __name__ == '__main__':
    exit(main())
