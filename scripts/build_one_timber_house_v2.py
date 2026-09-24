#!/usr/bin/env python3
"""Build one real 3x3 timber-shell house with the user's positional 3x3 roof.

This is the map-creator version of the user's 1-16 construction:
- 9 upper-floor roof positional pieces;
- lower-floor wall shell whose projected east/south faces complete the visual
  4x4 house footprint;
- matching timber windows and one closed wooden door.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from build_pp_map_001_lab import TILE, _Sprites, parse_all_items, render_item_thing
from extract_otb_item_client_ids import extract_records, parse_node

IDENT=b"OTBM";NS=0xFE;NE=0xFF;ESC=0xFD
ROOT=1;MAP=2;AREA=4;TILE_NODE=5;A_DESC=1;A_ITEM=9
BASE_X=34000;BASE_Y=34000
LOWER_Z=7;UPPER_Z=6;GROUND=101
ORIGIN=(4,4);SCENE_W=11;SCENE_H=10
WORLD_DELTA=(1,0,-1)

ROOF={(0,0):902,(1,0):907,(2,0):901,(0,1):903,(1,1):908,(2,1):904,(0,2):909,(1,2):905,(2,2):906}
WALL={"vertical":713,"horizontal":714,"pole":715,"corner":716}
WINDOW={"vertical":717,"horizontal":718}
DOOR=1029

HALF_ROLE_BY_MASK={
    0:"pole",1:"vertical",2:"horizontal",3:"corner",
    4:"pole",5:"vertical",6:"horizontal",7:"corner",
    8:"pole",9:"vertical",10:"horizontal",11:"corner",
    12:"pole",13:"vertical",14:"horizontal",15:"corner",
}

def u8(v):return struct.pack("<B",v)
def u16(v):return struct.pack("<H",v)
def s(v):
    b=v.encode();return u16(len(b))+b
def esc(data):
    out=bytearray()
    for b in data:
        if b in (NS,NE,ESC):out.append(ESC)
        out.append(b)
    return bytes(out)
def node(t,props=b"",children:Iterable[bytes]=()):
    return bytes((NS,t))+esc(props)+b"".join(children)+bytes((NE,))

def cardinal_mask(points,x,y):
    mask=0
    if (x,y-1) in points:mask|=1
    if (x-1,y) in points:mask|=2
    if (x+1,y) in points:mask|=4
    if (x,y+1) in points:mask|=8
    return mask

def boundary():
    ox,oy=ORIGIN;pts=set()
    for x in range(3):
        pts.add((ox+x,oy));pts.add((ox+x,oy+2))
    for y in range(3):
        pts.add((ox,oy+y));pts.add((ox+2,oy+y))
    return pts

def c2s_maps(otsp,client_ids):
    records=extract_records(otsp/"server_files"/"items.otb")
    by_client={}
    for sid,rec in records.items():by_client.setdefault(int(rec["client_id"]),[]).append((int(sid),rec))
    c2s={}
    for cid in sorted(client_ids):
        rows=by_client.get(cid,[])
        if len(rows)!=1:raise RuntimeError(f"client {cid} mapping count {len(rows)}")
        c2s[cid]=rows[0][0]
    return c2s,{sid:cid for cid,sid in c2s.items()},by_client

def build_area(z,stacks,c2s):
    children=[]
    for (x,y),stack in sorted(stacks.items(),key=lambda kv:(kv[0][1],kv[0][0])):
        props=bytearray((x,y))
        for cid in stack:props+=u8(A_ITEM)+u16(c2s[cid])
        children.append(node(TILE_NODE,bytes(props)))
    return node(AREA,struct.pack("<HHB",BASE_X,BASE_Y,z),children)

def inspect(payload,s2c):
    root,end=parse_node(payload,4)
    if end!=len(payload):raise RuntimeError("OTBM parse trailing bytes")
    maps=[x for x in root.children if x.node_type==MAP]
    if len(maps)!=1:raise RuntimeError("expected one MAP")
    out={}
    for area in maps[0].children:
        if area.node_type!=AREA:continue
        bx,by,bz=struct.unpack_from("<HHB",area.props,0)
        for tile in area.children:
            lx,ly=tile.props[:2];off=2;stack=[]
            while off<len(tile.props):
                if tile.props[off]!=A_ITEM:raise RuntimeError("unexpected tile attr")
                sid=struct.unpack_from("<H",tile.props,off+1)[0];off+=3
                stack.append(s2c[sid])
            out[(bx+lx,by+ly,bz)]=stack
    return out

def project(pos,camera):
    x,y,z=pos;cx,cy,cz=camera
    return ((x-cx)-(cz-z),(y-cy)-(cz-z))

def build_lower():
    lower={(x,y):[GROUND] for y in range(SCENE_H) for x in range(SCENE_W)}
    topo=boundary();roles={}
    east_window=(ORIGIN[0]+2,ORIGIN[1]+1)
    south_window=(ORIGIN[0],ORIGIN[1]+2)
    south_door=(ORIGIN[0]+1,ORIGIN[1]+2)
    for pos in sorted(topo,key=lambda p:(p[1],p[0])):
        role=HALF_ROLE_BY_MASK[cardinal_mask(topo,*pos)]
        cid=WALL[role]
        semantic=role
        if pos==east_window:
            if role!="vertical":raise RuntimeError("east window host alignment drift")
            cid=WINDOW["vertical"];semantic="window_vertical"
        elif pos==south_window:
            if role!="vertical":raise RuntimeError("south-left window host alignment drift")
            cid=WINDOW["vertical"];semantic="window_vertical"
        elif pos==south_door:
            if role!="horizontal":raise RuntimeError("south door host alignment drift")
            cid=DOOR;semantic="door_horizontal_closed"
        lower[pos].append(cid);roles[pos]=semantic
    return lower,roles

def build_upper():
    ox,oy=ORIGIN
    return {(ox+lx+WORLD_DELTA[0],oy+ly+WORLD_DELTA[1]):[cid] for (lx,ly),cid in ROOF.items()}

def emit(lower,upper,c2s):
    props=u8(A_DESC)+s("PP-MAP one timber house v2")
    root_props=struct.pack("<IHHII",2,65535,65535,3,55)
    return IDENT+node(ROOT,root_props,(node(MAP,props,(build_area(LOWER_Z,lower,c2s),build_area(UPPER_Z,upper,c2s))),))

def render(positions,items,sprites,path,debug=False):
    canvas=Image.new("RGBA",(620,470),(22,24,28,255))
    d=ImageDraw.Draw(canvas);font=ImageFont.load_default()
    d.text((8,8),"ONE TIMBER HOUSE — exact current OTSP sprites",fill=(240,240,240,255),font=font)
    d.text((8,25),"3x3 positional roof + framed timber shell + windows + closed door",fill=(185,192,202,255),font=font)
    camera=(BASE_X+ORIGIN[0],BASE_Y+ORIGIN[1],LOWER_Z);base=(250,175)
    for z in (LOWER_Z,UPPER_Z):
        for (x,y,zz),stack in sorted(((p,s) for p,s in positions.items() if p[2]==z),key=lambda kv:(kv[0][1],kv[0][0])):
            sx,sy=project((x,y,zz),camera)
            for cid in stack:
                obj=render_item_thing(items[cid],sprites)
                canvas.alpha_composite(obj,(base[0]+sx*TILE+TILE-obj.width,base[1]+sy*TILE+TILE-obj.height))
    if debug:
        # Show the 3x3 logical shell and its projected roof relation only.
        for iy in range(4):
            d.line((base[0],base[1]+iy*TILE,base[0]+3*TILE,base[1]+iy*TILE),fill=(255,255,255,180))
            d.line((base[0]+iy*TILE,base[1],base[0]+iy*TILE,base[1]+3*TILE),fill=(255,255,255,180))
    path.parent.mkdir(parents=True,exist_ok=True);canvas.convert("RGB").save(path,optimize=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--otsp",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    required={GROUND,DOOR,*WALL.values(),*WINDOW.values(),*ROOF.values()}
    c2s,s2c,by_client=c2s_maps(args.otsp,required)

    # Validate selected door as current blocking item; orientation flag is reported, not guessed.
    door_rec=by_client[DOOR][0][1]
    if not (int(door_rec["flags"]) & 1):raise RuntimeError(f"door {DOOR} is not blocking/closed candidate")
    door_horizontal_flag=bool(int(door_rec["flags"]) & (1<<18))
    door_vertical_flag=bool(int(door_rec["flags"]) & (1<<17))

    lower,roles=build_lower();upper=build_upper();payload=emit(lower,upper,c2s)
    positions=inspect(payload,s2c)
    pl={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in positions.items() if z==LOWER_Z}
    pu={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in positions.items() if z==UPPER_Z}
    if pl!=lower:raise RuntimeError("lower parseback mismatch")
    if pu!=upper:raise RuntimeError("upper parseback mismatch")
    if len(upper)!=9:raise RuntimeError("roof piece count changed")

    otbm=args.out/"one_timber_house_v2.otbm";otbm.write_bytes(payload)
    _,items=parse_all_items(args.otsp/"client_files"/"otsp.dat");sprites=_Sprites(args.otsp/"client_files"/"otsp.spr")
    render(positions,items,sprites,args.out/"one_timber_house_v2.png",False)
    render(positions,items,sprites,args.out/"one_timber_house_v2_debug.png",True)

    report={
      "project":"PP-MAP-001","result":"PASS","proof_key":"ONE_TIMBER_HOUSE_V2",
      "scope":"ONE_HOUSE_ONLY",
      "roof_matrix":[[902,907,901],[903,908,904],[909,905,906]],
      "wall_family":{"vertical":713,"horizontal":714,"pole":715,"corner":716,"vertical_window":717,"horizontal_window":718},
      "door":{"client_id":DOOR,"blocking":True,"horizontal_flag":door_horizontal_flag,"vertical_flag":door_vertical_flag},
      "wall_roles_by_position":{f"{x},{y}":r for (x,y),r in roles.items()},
      "world_delta":list(WORLD_DELTA),
      "otbm":{"file":otbm.name,"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),"exact_parseback":True},
      "render":{"file":"one_timber_house_v2.png","exact_current_dat_spr":True,"image_generation_used":False},
      "production_status":"UNCLASSIFIED"
    }
    (args.out/"one_timber_house_v2.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=="__main__":main()
