#!/usr/bin/env python3
"""Build the user's literal numbered 1-16 house with current OTSP assets.

Visible screen-space contract:
  01 02 03 04
  05 06 07 08
  09 10 11 12
  13 14 15 16

1-3 / 5-7 / 9-11 are the 3x3 red roof positional pieces.
4 / 8 / 12 are the visible east facade.
13-16 are the visible south facade.

This is intentionally one house only. No settlement, no resizing grammar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

from build_pp_map_001_lab import TILE, _Sprites, parse_all_items, render_item_thing
from extract_otb_item_client_ids import extract_records, parse_node

IDENT=b"OTBM"
NS=0xFE
NE=0xFF
ESC=0xFD
ROOT=1
MAP=2
AREA=4
TILE_NODE=5
A_DESC=1
A_ITEM=9

BASE_X=34000
BASE_Y=34000
LOWER_Z=7
UPPER_Z=6
GROUND=101

# The 3x3 red roof matrix is the real current positional roof vocabulary.
ROOF_MATRIX=[
    [902,907,901],
    [903,908,904],
    [909,905,906],
]

# Current light timber wall family and its matching visible variants.
# 786-789: base wall/pole/corner with the darker timber lower edge.
# 790/792: matching vertical/horizontal window substitutions.
# East screen column uses the east-west/horizontal wall face (787/792).
# South screen row uses the north-south/vertical facade face (786/790/1058).
# 1058 is the matching closed-looking vertical door piece.
EAST_WALL=661
EAST_WINDOW=663
SOUTH_START=662
SOUTH_WINDOW=664
SOUTH_DOOR=668
SOUTHEAST_CORNER=660

# Top-left visible numbered-cell screen tile within the preview/world.
SCREEN_ORIGIN=(2,2)
SCENE_W=8
SCENE_H=8

CELL_SPEC={
    1:("roof_nw",902,UPPER_Z,(0,0)),
    2:("roof_n",907,UPPER_Z,(1,0)),
    3:("roof_ne",901,UPPER_Z,(2,0)),
    4:("east_wall",EAST_WALL,LOWER_Z,(3,0)),
    5:("roof_w",903,UPPER_Z,(0,1)),
    6:("roof_fill",908,UPPER_Z,(1,1)),
    7:("roof_e",904,UPPER_Z,(2,1)),
    8:("east_window",EAST_WINDOW,LOWER_Z,(3,1)),
    9:("roof_sw",909,UPPER_Z,(0,2)),
    10:("roof_s",905,UPPER_Z,(1,2)),
    11:("roof_se",906,UPPER_Z,(2,2)),
    12:("east_wall_lower",EAST_WALL,LOWER_Z,(3,2)),
    13:("south_start",SOUTH_START,LOWER_Z,(0,3)),
    14:("south_window",SOUTH_WINDOW,LOWER_Z,(1,3)),
    15:("south_closed_door",SOUTH_DOOR,LOWER_Z,(2,3)),
    16:("south_east_corner",SOUTHEAST_CORNER,LOWER_Z,(3,3)),
}


def u8(v:int)->bytes:return struct.pack("<B",v)
def u16(v:int)->bytes:return struct.pack("<H",v)
def s(v:str)->bytes:
    b=v.encode("utf-8")
    return u16(len(b))+b

def esc(data:bytes)->bytes:
    out=bytearray()
    for b in data:
        if b in (NS,NE,ESC):out.append(ESC)
        out.append(b)
    return bytes(out)

def node(t:int,props:bytes=b"",children:Iterable[bytes]=())->bytes:
    return bytes((NS,t))+esc(props)+b"".join(children)+bytes((NE,))

def client_server_maps(otsp:Path, client_ids:set[int])->tuple[dict[int,int],dict[int,int]]:
    records=extract_records(otsp/"server_files"/"items.otb")
    by_client:dict[int,list[int]]={}
    for sid,rec in records.items():
        by_client.setdefault(int(rec["client_id"]),[]).append(int(sid))
    c2s={}
    for cid in sorted(client_ids):
        matches=by_client.get(cid,[])
        if len(matches)!=1:
            raise RuntimeError(f"client {cid} expected unique current server mapping, got {matches}")
        c2s[cid]=matches[0]
    return c2s,{sid:cid for cid,sid in c2s.items()}

def build_area(z:int,stacks:dict[tuple[int,int],list[int]],c2s:dict[int,int])->bytes:
    children=[]
    for (x,y),stack in sorted(stacks.items(),key=lambda kv:(kv[0][1],kv[0][0])):
        if not (0<=x<=255 and 0<=y<=255):
            raise RuntimeError("local OTBM coordinate outside AREA byte range")
        props=bytearray((x,y))
        for cid in stack:
            props += u8(A_ITEM)+u16(c2s[cid])
        children.append(node(TILE_NODE,bytes(props)))
    return node(AREA,struct.pack("<HHB",BASE_X,BASE_Y,z),children)

def inspect(payload:bytes,s2c:dict[int,int])->dict[tuple[int,int,int],list[int]]:
    if not payload.startswith(IDENT):raise RuntimeError("missing OTBM identifier")
    root,end=parse_node(payload,4)
    if end!=len(payload) and any(x!=0 for x in payload[end:]):
        raise RuntimeError("unexpected trailing OTBM bytes")
    maps=[x for x in root.children if x.node_type==MAP]
    if len(maps)!=1:raise RuntimeError("expected exactly one MAP")
    out={}
    for area in maps[0].children:
        if area.node_type!=AREA:continue
        bx,by,bz=struct.unpack_from("<HHB",area.props,0)
        for tile in area.children:
            if tile.node_type!=TILE_NODE:raise RuntimeError("unexpected AREA child")
            lx,ly=tile.props[0],tile.props[1]
            off=2; stack=[]
            while off<len(tile.props):
                if tile.props[off]!=A_ITEM:raise RuntimeError("unexpected tile attr")
                sid=struct.unpack_from("<H",tile.props,off+1)[0];off+=3
                if sid not in s2c:raise RuntimeError(f"unmapped emitted server id {sid}")
                stack.append(s2c[sid])
            out[(bx+lx,by+ly,bz)]=stack
    return out

def project(pos:tuple[int,int,int],camera:tuple[int,int,int])->tuple[int,int]:
    x,y,z=pos;cx,cy,cz=camera
    return ((x-cx)-(cz-z),(y-cy)-(cz-z))

def screen_to_local_world(screen:tuple[int,int],z:int)->tuple[int,int]:
    """Invert the pinned client projection for a desired screen tile."""
    sx,sy=screen
    dz=LOWER_Z-z
    # project world at camera z7 subtracts dz; therefore add dz in world.
    return (SCREEN_ORIGIN[0]+sx+dz, SCREEN_ORIGIN[1]+sy+dz)

def build_layers()->tuple[dict[tuple[int,int],list[int]],dict[tuple[int,int],list[int]],list[dict[str,Any]]]:
    lower={(x,y):[GROUND] for y in range(SCENE_H) for x in range(SCENE_W)}
    upper={}
    realized=[]
    for number in range(1,17):
        role,cid,z,screen=CELL_SPEC[number]
        wx,wy=screen_to_local_world(screen,z)
        if z==LOWER_Z:
            lower[(wx,wy)].append(cid)
        else:
            if (wx,wy) in upper:raise RuntimeError("upper collision")
            upper[(wx,wy)]=[cid]
        realized.append({
            "number":number,"role":role,"client_id":cid,"z":z,
            "screen_cell":list(screen),"world_local":[wx,wy],
        })
    return lower,upper,realized

def emit(lower,upper,c2s)->bytes:
    props=u8(A_DESC)+s("PP-MAP numbered house v4 - literal user 1-16 timber-band assembly")
    root_props=struct.pack("<IHHII",2,65535,65535,3,55)
    return IDENT+node(ROOT,root_props,(
        node(MAP,props,(
            build_area(LOWER_Z,lower,c2s),
            build_area(UPPER_Z,upper,c2s),
        )),
    ))

def verify_screen_contract(positions,realized)->None:
    camera=(BASE_X+SCREEN_ORIGIN[0],BASE_Y+SCREEN_ORIGIN[1],LOWER_Z)
    for row in realized:
        wx,wy=row["world_local"];z=row["z"];cid=row["client_id"]
        world=(BASE_X+wx,BASE_Y+wy,z)
        if cid not in positions.get(world,[]):
            raise RuntimeError(f"cell {row['number']} emitted stack mismatch")
        if list(project(world,camera))!=row["screen_cell"]:
            raise RuntimeError(
                f"cell {row['number']} projection mismatch "
                f"{project(world,camera)} != {tuple(row['screen_cell'])}"
            )

def render(positions,items,sprites,path:Path,debug:bool)->None:
    image=Image.new("RGBA",(660,560),(22,24,28,255))
    draw=ImageDraw.Draw(image);font=ImageFont.load_default()
    title="PP-MAP NUMBERED HOUSE V1 — exact current OTSP sprites"
    draw.text((10,10),title,fill=(240,240,240,255),font=font)
    if debug:
        draw.text((10,27),"literal 1-16 screen-space construction; no image generation",fill=(185,192,202,255),font=font)
    camera=(BASE_X+SCREEN_ORIGIN[0],BASE_Y+SCREEN_ORIGIN[1],LOWER_Z)
    base_x,base_y=230,145

    # Ground + lower facade first.
    for (x,y,z),stack in sorted(
        ((p,st) for p,st in positions.items() if p[2]==LOWER_Z),
        key=lambda kv:(kv[0][1],kv[0][0])
    ):
        sx,sy=project((x,y,z),camera)
        for cid in stack:
            obj=render_item_thing(items[cid],sprites)
            image.alpha_composite(obj,(base_x+sx*TILE+TILE-obj.width,base_y+sy*TILE+TILE-obj.height))

    # Roof floor after lower floor.
    for (x,y,z),stack in sorted(
        ((p,st) for p,st in positions.items() if p[2]==UPPER_Z),
        key=lambda kv:(kv[0][1],kv[0][0])
    ):
        sx,sy=project((x,y,z),camera)
        for cid in stack:
            obj=render_item_thing(items[cid],sprites)
            image.alpha_composite(obj,(base_x+sx*TILE+TILE-obj.width,base_y+sy*TILE+TILE-obj.height))

    if debug:
        # Number the exact screen cells without altering the clean render.
        for n in range(1,17):
            _,_,_,(sx,sy)=CELL_SPEC[n]
            x=base_x+sx*TILE;y=base_y+sy*TILE
            draw.rectangle((x,y,x+TILE-1,y+TILE-1),outline=(255,255,255,150),width=1)
            draw.text((x+2,y+2),str(n),fill=(255,235,60,255),font=font)
    path.parent.mkdir(parents=True,exist_ok=True)
    image.convert("RGB").save(path,optimize=True)

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--otsp",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)

    # Freeze the user's roof matrix exactly.
    if [[CELL_SPEC[1][1],CELL_SPEC[2][1],CELL_SPEC[3][1]],
        [CELL_SPEC[5][1],CELL_SPEC[6][1],CELL_SPEC[7][1]],
        [CELL_SPEC[9][1],CELL_SPEC[10][1],CELL_SPEC[11][1]]] != ROOF_MATRIX:
        raise RuntimeError("numbered roof matrix drifted")

    required={GROUND}
    required.update(row[1] for row in CELL_SPEC.values())
    c2s,s2c=client_server_maps(args.otsp,required)
    lower,upper,realized=build_layers()
    payload=emit(lower,upper,c2s)
    otbm=args.out/"numbered_house_v4.otbm"
    otbm.write_bytes(payload)
    positions=inspect(payload,s2c)

    parsed_lower={(x-BASE_X,y-BASE_Y):stack for (x,y,z),stack in positions.items() if z==LOWER_Z}
    parsed_upper={(x-BASE_X,y-BASE_Y):stack for (x,y,z),stack in positions.items() if z==UPPER_Z}
    if parsed_lower!=lower:raise RuntimeError("lower exact parseback mismatch")
    if parsed_upper!=upper:raise RuntimeError("upper exact parseback mismatch")
    verify_screen_contract(positions,realized)

    _,items=parse_all_items(args.otsp/"client_files"/"otsp.dat")
    sprites=_Sprites(args.otsp/"client_files"/"otsp.spr")
    render(positions,items,sprites,args.out/"numbered_house_v4.png",False)
    render(positions,items,sprites,args.out/"numbered_house_v4_debug.png",True)

    report={
        "project":"PP-MAP-001",
        "result":"PASS",
        "proof_key":"USER_NUMBERED_HOUSE_1_16_V4_TIMBER_BAND",
        "scope":"ONE_HOUSE_ONLY",
        "source_otsp_commit":"ae88e1828671b349e729dd21177dde15ea41e123",
        "screen_matrix":[
            [1,2,3,4],
            [5,6,7,8],
            [9,10,11,12],
            [13,14,15,16],
        ],
        "roof_matrix":ROOF_MATRIX,
        "cells":realized,
        "otbm":{
            "file":"numbered_house_v1.otbm",
            "bytes":len(payload),
            "sha256":hashlib.sha256(payload).hexdigest(),
            "exact_stack_parseback":True,
        },
        "render":{
            "clean":"numbered_house_v1.png",
            "debug_numbered":"numbered_house_v1_debug.png",
            "exact_current_dat_spr":True,
            "image_generation_used":False,
        },
        "claims":{
            "literal_user_numbered_screen_assembly":True,
            "roof_resized":False,
            "settlement_or_compound_generated":False,
            "general_house_grammar_claimed":False,
        },
        "production_status":"UNCLASSIFIED",
    }
    (args.out/"numbered_house_v4.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=="__main__":
    main()

# public-ci-trigger: numbered-house-v1
