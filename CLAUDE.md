# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project converts Shopify product exports to Amazon Seller Central upload format for the Spectral Paints product line. It transforms CSV exports from Shopify into tab-delimited `.txt` files matching Amazon's PAINT category template.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Convert a Shopify CSV to Amazon format
python3 shopify_to_amazon.py <input.csv>
python3 shopify_to_amazon.py <input.csv> -o custom_output.txt

# Read Excel template (requires openpyxl)
pip install openpyxl
```

## Architecture

### Data Flow
1. **Input**: Shopify CSV exports with 68 columns (Handle, Title, Variant SKU, etc.)
2. **Template**: `PAINT.xlsm` - Amazon's official 286-column template for paint products
3. **Output**: Tab-delimited `.txt` files with 3 header rows + data rows

### Key Files
- `shopify_to_amazon.py` - Main converter script
- `amazon_template_headers.json` - Extracted column structure from PAINT.xlsm (286 columns)
- `PAINT.xlsm` - Amazon's official template with Valid Values sheet for field validation

### Shopify Variant Handling
Shopify exports use a parent/child structure where only the first variant row contains the Title and Body HTML. The converter tracks parent data and inherits it to subsequent variant rows.

### Amazon Template Structure
- Row 1: Instructions
- Row 2: Category headers (Listing Identity, Product Identity, Offer, etc.)
- Row 3: Column names (286 total)
- Row 4+: Product data

### Field Mappings
Key Shopify → Amazon mappings:
- `Variant SKU` → SKU
- `Title` + `Option1 Value` → Item Name
- `Variant Price` → Your Price USD
- `Variant Inventory Qty` → Quantity (US)
- `Body (HTML)` → Product Description, Bullet Points
- `UPC metafield` → Product Id

### Default Values
- Brand Name: "Spectral Paints"
- Product Type: "PAINT"
- Country of Origin: "United States"
- Dangerous Goods: GHS (Flammable, Irritant)
- Listing Action: "Create or Replace (Full Update)"
