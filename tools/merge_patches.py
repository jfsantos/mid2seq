#!/usr/bin/env python3
"""
merge_patches.py — Merge multiple FM patch JSON files into one saturn_kit.py config.

Usage:
  # Export JSON from each VST instance (Copy JSON button), save to files:
  python3 tools/merge_patches.py piano.json bass.json brass.json -o my_kit.json
  python3 tools/saturn_kit.py --config my_kit.json -o my_kit

  # Or pipe from clipboard on macOS:
  pbpaste > patch1.json   # paste first export
  pbpaste > patch2.json   # paste second export
  python3 tools/merge_patches.py patch*.json -o kit.json
"""

import json
import sys
import os


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Merge FM patch JSON files')
    parser.add_argument('files', nargs='+', help='JSON files to merge')
    parser.add_argument('-o', '--output', default='merged_patches.json',
                        help='Output JSON file (default: merged_patches.json)')
    args = parser.parse_args()

    instruments = []
    seen_programs = set()

    for path in args.files:
        with open(path) as f:
            data = json.load(f)

        if 'instruments' in data:
            for inst in data['instruments']:
                prog = inst.get('program', len(instruments))
                if prog in seen_programs:
                    print(f"  WARNING: duplicate program {prog} in {path}, "
                          f"reassigning to {max(seen_programs) + 1}")
                    prog = max(seen_programs) + 1
                    inst['program'] = prog
                seen_programs.add(prog)
                instruments.append(inst)
                print(f"  [{prog:2d}] {inst.get('name', '?'):20s} "
                      f"({len(inst.get('fm_ops', []))} ops) from {path}")
        else:
            print(f"  WARNING: {path} has no 'instruments' array, skipping")

    # Sort by program number
    instruments.sort(key=lambda x: x.get('program', 0))

    config = {'instruments': instruments}
    with open(args.output, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\n[merge] {args.output}: {len(instruments)} instruments")
    print(f"  Use with: python3 tools/saturn_kit.py --config {args.output} -o my_kit")


if __name__ == '__main__':
    main()
