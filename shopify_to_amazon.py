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
    # Listing Identity
    amazon_row['SKU'] = shopify_product.get('Variant SKU', '')
    amazon_row['Listing Action'] = 'Create or Replace (Full Update)'

    # Product Identity
    amazon_row['Product Type'] = 'PAINT'
    amazon_row['Item Name'] = item_name[:500]
    amazon_row['Brand Name'] = 'Spectral Paints'
    amazon_row['Product Id Type'] = 'UPC' if upc else 'GTIN Exempt'
    amazon_row['Product Id'] = upc
    amazon_row['Item Type Keyword'] = 'paint'
    amazon_row['Manufacturer'] = 'Spectral Paints'

    # Offer
    amazon_row['Item Condition'] = 'New'
    amazon_row['List Price'] = shopify_product.get('Variant Price', '')

    # Offer (US)
    amazon_row['Fulfillment Channel Code (US)'] = 'DEFAULT'
    amazon_row['Quantity (US)'] = shopify_product.get('Variant Inventory Qty', '')
    amazon_row['Your Price USD (Sell on Amazon, US)'] = shopify_product.get('Variant Price', '')

    # Product Details
    amazon_row['Product Description'] = description[:2000]
    amazon_row['Number of Items'] = '1'
    amazon_row['Color'] = color
    amazon_row['Size'] = size
    amazon_row['Paint Type'] = paint_type
    amazon_row['Finish Type'] = finish

    # Handle duplicate column names - Bullet Points are at indices 74-78 (cols 75-79)
    # We need to set them by position since there are multiple "Bullet Point" columns

    # Safety & Compliance
    amazon_row['Country of Origin'] = 'United States'
    amazon_row['Are batteries required?'] = 'No'
    amazon_row['Are batteries included?'] = 'No'

    # Dangerous Goods - handle duplicate column names
    amazon_row['Dangerous Goods Regulations'] = 'GHS'

    # Images
    amazon_row['Main Image URL'] = main_image

    return amazon_row, bullets


def write_amazon_txt(products, bullets_list, output_path, template_headers):
    """Write products to Amazon tab-delimited format with proper headers."""

    instructions = template_headers['instructions']
    categories = template_headers['categories']
    columns = template_headers['columns']
    num_cols = len(columns)

    # Ensure all header rows have exactly num_cols columns
    while len(instructions) < num_cols:
        instructions.append('')
    while len(categories) < num_cols:
        categories.append('')

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='\t')

        # Row 1: Instructions
        writer.writerow(instructions[:num_cols])

        # Row 2: Category headers
        writer.writerow(categories[:num_cols])

        # Row 3: Column names
        writer.writerow(columns)

        # Data rows
        for product, bullets in zip(products, bullets_list):
            row = []
            bullet_idx = 0
            ghs_idx = 0

            for i, col_name in enumerate(columns):
                if col_name == 'Bullet Point':
                    # Handle multiple Bullet Point columns (indices 74-78)
                    if bullet_idx < len(bullets):
                        row.append(bullets[bullet_idx][:500] if bullets[bullet_idx] else '')
                    else:
                        row.append('')
                    bullet_idx += 1
                elif col_name == 'GHS Class':
                    # Handle multiple GHS Class columns
                    if ghs_idx == 0:
                        row.append('Flammable')
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
    print(f"File includes 3 header rows + {count} data rows")
    return 0


if __name__ == '__main__':
    exit(main())
