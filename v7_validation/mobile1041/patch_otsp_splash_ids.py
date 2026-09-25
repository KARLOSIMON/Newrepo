#!/usr/bin/env python3
"""Align pinned historical TFS splash constants with pinned OTSP item IDs.

Historical TFS 10.41 hardcodes:
  ITEM_FULLSPLASH  = 2016
  ITEM_SMALLSPLASH = 2019

Pinned OTSP moved the same two three-stage splash/pool chains to:
  full:  2221 -> 2222 -> 2223
  small: 2224 -> 2225 -> 2226

OTSP items.otb confirms 2016/2019 are group 0 objects while 2221-2226 are
ITEM_GROUP_SPLASH (11). This patch changes only the two engine item constants;
fluid subtype, blood/slime color mapping, decay, combat damage and effect logic
remain native TFS behavior.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

START=0xFE
END=0xFF
ESCAPE=0xFD
ATTR_SERVERID=0x10
ATTR_CLIENTID=0x11
SPLASH_GROUP=11
FULL_OLD=2016
SMALL_OLD=2019
FULL_NEW=2221
SMALL_NEW=2224
MARKER="POCKETPVP_OTSP_SPLASH_IDS_V1"

def parse_node(data:bytes, off:int):
    if data[off] != START:
        raise ValueError(f"expected node at {off}")
    node_type=data[off+1]; off += 2
    props=bytearray(); children=[]
    while off < len(data):
        b=data[off]
        if b == ESCAPE:
            props.append(data[off+1]); off += 2; continue
        if b == START:
            child,off=parse_node(data,off); children.append(child); continue
        if b == END:
            return (node_type,bytes(props),children),off+1
        props.append(b); off += 1
    raise ValueError("unterminated OTB node")

def item_record(node):
    node_type,props,_=node
    if len(props)<4: return None
    off=4; sid=cid=None
    while off<len(props):
        attr=props[off]
        length=struct.unpack_from("<H",props,off+1)[0]
        off += 3
        payload=props[off:off+length]; off += length
        if attr==ATTR_SERVERID and length==2: sid=struct.unpack("<H",payload)[0]
        elif attr==ATTR_CLIENTID and length==2: cid=struct.unpack("<H",payload)[0]
    if sid is None or cid is None: return None
    return sid,cid,node_type

def verify_otsp(otb:Path):
    data=otb.read_bytes()
    root,end=parse_node(data,4)
    records={}
    for child in root[2]:
        r=item_record(child)
        if r: records[r[0]]=r
    for sid in (FULL_NEW,SMALL_NEW):
        if sid not in records or records[sid][2] != SPLASH_GROUP:
            raise SystemExit(f"OTSP expected splash id {sid} is not group {SPLASH_GROUP}: {records.get(sid)}")
    for sid in (FULL_OLD,SMALL_OLD):
        if sid in records and records[sid][2] == SPLASH_GROUP:
            raise SystemExit(f"historical id {sid} unexpectedly became a splash; review migration")
    print(f"OTSP splash mapping verified: full={FULL_NEW}, small={SMALL_NEW}")

def patch(tfs:Path,otb:Path):
    verify_otsp(otb)
    path=tfs/"src"/"const.h"
    text=path.read_text(encoding="utf-8")
    if MARKER in text:
        print("OTSP splash constants already patched")
        return
    old="""	ITEM_FULLSPLASH = 2016,
	ITEM_SMALLSPLASH = 2019,"""
    new=f"""	// {MARKER}
	ITEM_FULLSPLASH = {FULL_NEW},
	ITEM_SMALLSPLASH = {SMALL_NEW},"""
    if old not in text:
        raise SystemExit("historical TFS splash constants anchor changed")
    text=text.replace(old,new,1)
    path.write_text(text,encoding="utf-8")
    verify=path.read_text(encoding="utf-8")
    assert MARKER in verify
    assert f"ITEM_FULLSPLASH = {FULL_NEW}" in verify
    assert f"ITEM_SMALLSPLASH = {SMALL_NEW}" in verify
    print("TFS -> OTSP splash constants patch: PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("tfs",type=Path)
    ap.add_argument("otb",type=Path)
    args=ap.parse_args()
    patch(args.tfs,args.otb)

if __name__=="__main__":
    main()
