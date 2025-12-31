#!/usr/bin/env python3
"""
Shopify to Amazon PAINT Template Converter

Converts Shopify product export CSV files to Amazon's tab-delimited
upload format based on the PAINT.xlsm template.
"""

import csv
import argparse
import json
from pathlib import Path
from html import unescape
import re

# Path to template headers JSON (extracted from PAINT.xlsm)
TEMPLATE_HEADERS_FILE = Path(__file__).parent / 'amazon_template_headers.json'


def load_template_headers():
    """Load the Amazon template headers from JSON file."""
    with open(TEMPLATE_HEADERS_FILE, 'r') as f:
        return json.load(f)


def strip_html(html_text):
    """Remove HTML tags and decode entities."""
    if not html_text:
        return ''
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Decode HTML entities
    text = unescape(text)
    # Normalize whitespace
    text = ' '.join(text.split())
    return text.strip()


def extract_bullet_points(html_text, max_bullets=5):
    """Extract bullet points from HTML list items or create from description."""
    if not html_text:
        return [''] * max_bullets

    bullets = []

    # Try to find list items
    li_pattern = re.compile(r'<li[^>]*>(.*?)</li>', re.IGNORECASE | re.DOTALL)
    matches = li_pattern.findall(html_text)

    if matches:
        for match in matches[:max_bullets]:
            bullet = strip_html(match).strip()
            if bullet:
                bullets.append(bullet)

    # Pad with empty strings
    while len(bullets) < max_bullets:
        bullets.append('')

    return bullets[:max_bullets]


def read_shopify_csv(filepath):
    """Read Shopify CSV and handle variant inheritance."""
    products = []

    # Try different encodings
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

    # Track parent product data for variants
    parent_title = ''
    parent_body = ''
    parent_handle = ''
    parent_vendor = ''
    parent_type = ''
    parent_tags = ''

    for row in rows:
        # If this row has a Title, it's a new parent product
        if row.get('Title', '').strip():
            parent_title = row.get('Title', '')
            parent_body = row.get('Body (HTML)', '')
            parent_handle = row.get('Handle', '')
            parent_vendor = row.get('Vendor', '')
            parent_type = row.get('Type', '')
            parent_tags = row.get('Tags', '')

        # Skip rows without SKU
        sku = row.get('Variant SKU', '').strip()
        if not sku:
            continue

        # Create product with inherited parent data
        product = dict(row)
        product['Variant SKU'] = sku
        product['parent_title'] = parent_title
        product['parent_body'] = parent_body
        product['parent_handle'] = parent_handle
        product['parent_vendor'] = parent_vendor
        product['parent_type'] = parent_type
        product['parent_tags'] = parent_tags

        products.append(product)

    return products


def map_to_amazon(shopify_product, column_names):
    """Map a Shopify product to Amazon template format."""

    # Initialize all columns with empty strings
    amazon_row = {col: '' for col in column_names}

    # Build the Item Name from title + variant option
    title = shopify_product.get('parent_title', '') or shopify_product.get('Title', '')
    option_value = shopify_product.get('Option1 Value', '').strip()

    if option_value and option_value.lower() not in title.lower():
        item_name = f"{title} - {option_value}"
    else:
        item_name = title

    # Get bullet points from HTML body (use parent_body for inherited descriptions)
    body_html = shopify_product.get('Body (HTML)', '').strip() or shopify_product.get('parent_body', '')
    bullets = extract_bullet_points(body_html)
    description = strip_html(body_html)

    # Generate bullet points from description if none extracted from HTML lists
    if not any(bullets):
        if description:
            bullets[0] = description[:500]

    # Get UPC if available
    upc = shopify_product.get('UPC (product.metafields.facts.upc)', '').strip()

    # Get metafields
    color = shopify_product.get('Color (product.metafields.shopify.color-pattern)', '')
    finish = shopify_product.get('Paint finish (product.metafields.shopify.paint-finish)', '')
    paint_type = shopify_product.get('Vehicle paint type (product.metafields.shopify.vehicle-paint-type)', '')

    # Determine size from option or title
    size = shopify_product.get('Option1 Value', '')
    if 'gallon' in title.lower() or 'gallon' in size.lower():
        size = 'Gallon'
    elif 'quart' in title.lower() or 'quart' in size.lower():
        size = 'Quart'

    # Get image URLs
    main_image = shopify_product.get('Variant Image', '') or shopify_product.get('Image Src', '')

    # Map to Amazon columns
    # Error/Suggestion counts (Amazon fills these, but we set defaults)
    amazon_row['Number of attributes with errors'] = '0'
    amazon_row['Number of attributes with other suggestions'] = '0'

    # Listing Identity
    amazon_row['SKU'] = shopify_product.get('Variant SKU', '')
    amazon_row['Listing Action'] = 'Create or Replace (Full Update)'

    # Product Identity
    amazon_row['Product Type'] = 'PAINT'
    amazon_row['Item Name'] = item_name[:500]
    amazon_row['Brand Name'] = 'Spectral Paints'
    amazon_row['Product Id Type'] = 'UPC' if upc else 'GTIN Exempt'
    amazon_row['Product Id'] = upc
    # Use the full browse path for automotive paint products
    amazon_row['Item Type Keyword'] = 'Automotive > Paint & Paint Supplies > Paints & Primers > Clear Coats (automotive-clear-coat-paints)'
    amazon_row['Manufacturer'] = 'Spectral Paints'

    # Offer
    amazon_row['Item Condition'] = 'New'
    amazon_row['List Price'] = shopify_product.get('Variant Price', '')

    # Offer (US)
    amazon_row['Fulfillment Channel Code (US)'] = 'DEFAULT'
    amazon_row['Quantity (US)'] = shopify_product.get('Variant Inventory Qty', '')
    amazon_row['Merchant Shipping Group (US)'] = 'Migrated Template'

    # Product Details
    amazon_row['Product Description'] = description[:2000]
    amazon_row['Number of Items'] = '1'
    amazon_row['Color'] = color if color else 'Clear'
    amazon_row['Color Code'] = color if color else 'Clear'
    amazon_row['Size'] = size
    amazon_row['Part Number'] = shopify_product.get('Variant SKU', '')
    amazon_row['Surface Recommendation'] = 'Metal'
    amazon_row['Coverage'] = '0'
    amazon_row['Paint Type'] = paint_type if paint_type else 'Spray'
    amazon_row['Finish Type'] = finish if finish else 'Metallic'
    amazon_row['Item Form'] = 'Aerosol'
    amazon_row['Unit Count'] = '1'
    amazon_row['Unit Count Type'] = 'Fl Oz'
    amazon_row['Specific Uses for Product'] = 'Exterior'

    # Volume - derive from size
    if 'quart' in size.lower():
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Quarts'
    elif 'gallon' in size.lower():
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Gallons'
    elif 'pint' in size.lower():
        amazon_row['Item Volume'] = '1'
        amazon_row['Item Volume Unit'] = 'Pints'

    # Safety & Compliance
    amazon_row['Country of Origin'] = 'United States'
    amazon_row['Are batteries required?'] = 'No'
    amazon_row['Are batteries included?'] = 'No'

    # Safety Data Sheet URL
    amazon_row['Safety Data Sheet (SDS or MSDS) URL'] = 'spectralpaints.biz'

    # Images
    amazon_row['Main Image URL'] = main_image

    return amazon_row, bullets


def write_amazon_txt(products, bullets_list, output_path, template_headers):
    """Write products to Amazon tab-delimited format with proper headers."""

    settings = template_headers['settings']
    instructions = template_headers['instructions']
    categories = template_headers['categories']
    columns = template_headers['columns']
    attributes = template_headers['attributes']
    example_row = template_headers.get('example_row', [])
    num_cols = len(columns)

    # Ensure all header rows have exactly num_cols columns
    while len(settings) < num_cols:
        settings.append('')
    while len(instructions) < num_cols:
        instructions.append('')
    while len(categories) < num_cols:
        categories.append('')
    while len(attributes) < num_cols:
        attributes.append('')
    while len(example_row) < num_cols:
        example_row.append('')

    with open(output_path, 'w', encoding='cp1252', newline='') as f:
        # Write header rows directly (they already have proper quoting from template)
        # Use CRLF line endings to match Amazon template
        f.write('\t'.join(settings[:num_cols]) + '\r\n')
        f.write('\t'.join(instructions[:num_cols]) + '\r\n')
        f.write('\t'.join(categories[:num_cols]) + '\r\n')
        f.write('\t'.join(columns[:num_cols]) + '\r\n')
        f.write('\t'.join(attributes[:num_cols]) + '\r\n')

        # Write example row (ABC123) - required by Amazon template
        f.write('\t'.join(example_row[:num_cols]) + '\r\n')

        # Use csv writer for data rows (also needs CRLF)
        writer = csv.writer(f, delimiter='\t', lineterminator='\r\n')

        # Data rows
        for product, bullets in zip(products, bullets_list):
            row = []
            bullet_idx = 0
            ghs_idx = 0
            dg_idx = 0  # Dangerous Goods Regulations index

            for i, col_name in enumerate(columns):
                if col_name == 'Bullet Point':
                    # Handle multiple Bullet Point columns
                    if bullet_idx < len(bullets):
                        row.append(bullets[bullet_idx][:500] if bullets[bullet_idx] else '')
                    else:
                        row.append('')
                    bullet_idx += 1
                elif col_name == 'Dangerous Goods Regulations':
                    # Handle multiple Dangerous Goods columns: Other, GHS, GHS, GHS, GHS
                    if dg_idx == 0:
                        row.append('Other')
                    elif dg_idx <= 4:
                        row.append('GHS')
                    else:
                        row.append('')
                    dg_idx += 1
                elif col_name == 'GHS Class':
                    # Handle multiple GHS Class columns
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

            # Ensure row has exactly num_cols columns
            while len(row) < num_cols:
                row.append('')

            writer.writerow(row[:num_cols])

    return len(products)


def main():
    parser = argparse.ArgumentParser(
        description='Convert Shopify CSV to Amazon PAINT template format'
    )
    parser.add_argument('input_csv', help='Path to Shopify CSV export file')
    parser.add_argument('-o', '--output', help='Output .txt file path (default: <input>_amazon.txt)')

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

    print(f"Reading Shopify CSV: {input_path}")
    products = read_shopify_csv(input_path)
    print(f"Found {len(products)} products/variants")

    print("Mapping to Amazon format...")
    amazon_products = []
    bullets_list = []
    for p in products:
        amazon_row, bullets = map_to_amazon(p, columns)
        amazon_products.append(amazon_row)
        bullets_list.append(bullets)

    print(f"Writing to: {output_path}")
    count = write_amazon_txt(amazon_products, bullets_list, output_path, template_headers)

    print(f"Done! Wrote {count} products to {output_path}")
    print(f"File includes 6 header rows (5 headers + 1 example) + {count} data rows")
    return 0


if __name__ == '__main__':
    exit(main())
