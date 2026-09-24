#!/usr/bin/env python3
from pathlib import Path
from build_pp_map_001_lab import (
    _Sprites, parse_all_items, parse_tilesets, parse_item_labels, build_atlas_pages
)

ROOT=Path(__file__).resolve().parents[1]
OTSP=ROOT/".work"/"otsp-source"
OUT=ROOT/".work"/"house-parts-atlas"

def main():
    client=OTSP/"client_files"; rme=OTSP/"rme_files"
    header,items=parse_all_items(client/"otsp.dat")
    sprites=_Sprites(client/"otsp.spr")
    by_tileset,_=parse_tilesets(rme/"tilesets.xml")
    labels=parse_item_labels(rme/"items.xml")
    OUT.mkdir(parents=True,exist_ok=True)
    reports=[]
    for category in ("Walls","Doors and Windows","Roofs"):
        ids=[i for i in by_tileset.get(category,[]) if 100<=i<=header["item_max"]]
        reports.append(build_atlas_pages(
            category=category,ids=ids,items=items,sprites=sprites,labels=labels,out_dir=OUT
        ))
    import json
    (OUT/"reports.json").write_text(json.dumps(reports,indent=2)+"\n")
    print(json.dumps(reports,indent=2))

if __name__=="__main__": main()
