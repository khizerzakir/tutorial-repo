#!/usr/bin/env python3
"""
CDO Grid Generator
Generates grid.txt dynamically based on resolution from config_resolution.yaml
Usage: python3 generate_grid.py --resolution 0.05
"""

import yaml
import argparse
from pathlib import Path


def calculate_grid_size(resolution, lon_min, lon_max, lat_min, lat_max):
    """Calculate xsize and ysize based on resolution and domain"""
    xsize = int(round((lon_max - lon_min) / resolution))
    ysize = int(round((lat_max - lat_min) / resolution))
    return xsize, ysize


def generate_grid(resolution, domain):
    """Generate grid.txt content"""
    xsize, ysize = calculate_grid_size(
        resolution,
        domain['lon_min'],
        domain['lon_max'],
        domain['lat_min'],
        domain['lat_max']
    )
    
    grid_content = (
        f"gridtype = lonlat\n"
        f"xsize = {xsize}\n"
        f"ysize = {ysize}\n"
        f"xfirst = {domain['lon_min']}\n"
        f"yfirst = {domain['lat_min']}\n"
        f"xinc = {resolution}\n"
        f"yinc = {resolution}\n"
    )
    
    return grid_content, xsize, ysize


def main():
    parser = argparse.ArgumentParser(
        description='Generate CDO grid.txt based on resolution'
    )
    parser.add_argument(
        '--resolution', '-r',
        type=float,
        required=True,
        help='Resolution in degrees (e.g., 0.05, 0.1)'
    )
    parser.add_argument(
        '--config', '-c',
        default='config_resolution.yaml',
        help='Config file path (default: config_resolution.yaml)'
    )
    parser.add_argument(
        '--output', '-o',
        default='grid.txt',
        help='Output grid file (default: grid.txt)'
    )
    
    args = parser.parse_args()
    
    # Load config
    config_file = Path(args.config)
    if not config_file.exists():
        print(f"Error: Config file not found: {config_file}")
        return 1
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    domain = config['domain']
    
    # Generate grid
    grid_content, xsize, ysize = generate_grid(args.resolution, domain)
    
    # Write to file
    output_file = Path(args.output)
    output_file.write_text(grid_content)
    
    # Print info
    print(f"✓ Generated {args.output}")
    print(f"  Resolution: {args.resolution}°")
    print(f"  Grid Size: {xsize} × {ysize} ({xsize * ysize:,} points)")
    print(f"  Domain: [{domain['lon_min']}, {domain['lon_max']}]° × "
          f"[{domain['lat_min']}, {domain['lat_max']}]°")
    
    return 0


if __name__ == "__main__":
    exit(main())
