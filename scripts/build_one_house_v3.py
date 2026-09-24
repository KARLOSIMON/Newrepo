#!/usr/bin/env python3
"""One house v3: user's red roof assembly + cream/timber-band facade."""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path
from typing import Iterable
from PIL import Image, ImageDraw, ImageFont
from build_pp_map_001_lab import TILE,_Sprites,parse_all_items,render_item_thing
from extract_otb_item_client_ids import extract_records,parse_node

IDENT=b"OTBM";NS=0xFE;NE=0xFF;ESC=0xFD
ROOT=1;MAP=2;AREA=4;TILE_NODE=5;A_DESC=1;A_ITEM=9
BASE_X=34000;BASE_Y=34000;LOWER_Z=7;UPPER_Z=6;GROUND=101
ORIGIN=(4,4);SCENE_W=11;SCENE_H=10;WORLD_DELTA=(1,0,-1)

ROOF={(0,0):902,(1,0):907,(2,0):901,(0,1):903,(1,1):908,(2,1):904,(0,2):909,(1,2):905,(2,2):906}

# Structural cream/timber wall family.
BASE_WALL={"vertical":651,"horizontal":652,"pole":653,"corner":657}

# Exposed facade variants from the SAME visual family.
FACADE={
    "east_wall":661,
    "east_window":663,
    "south_wall":662,
    "south_window":664,
    "south_door":668,
    "south_east_corner":660,
}

HALF={0:"pole",1:"vertical",2:"horizontal",3:"corner",4:"pole",5:"vertical",6:"horizontal",7:"corner",8:"pole",9:"vertical",10:"horizontal",11:"corner",12:"pole",13:"vertical",14:"horizontal",15:"corner"}

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
def cardinal(points,x,y):
 m=0
 if (x,y-1) in points:m|=1
 if (x-1,y) in points:m|=2
 if (x+1,y) in points:m|=4
 if (x,y+1) in points:m|=8
 return m
def boundary():
 ox,oy=ORIGIN;pts=set()
 for x in range(3):pts.add((ox+x,oy));pts.add((ox+x,oy+2))
 for y in range(3):pts.add((ox,oy+y));pts.add((ox+2,oy+y))
 return pts
def maps(otsp,ids):
 recs=extract_records(otsp/"server_files"/"items.otb");bc={}
 for sid,r in recs.items():bc.setdefault(int(r["client_id"]),[]).append(int(sid))
 c2s={}
 for cid in sorted(ids):
  ms=bc.get(cid,[])
  if len(ms)!=1:raise RuntimeError(f"client {cid} mapping {ms}")
  c2s[cid]=ms[0]
 return c2s,{sid:cid for cid,sid in c2s.items()}
def area(z,stacks,c2s):
 kids=[]
 for (x,y),stack in sorted(stacks.items(),key=lambda kv:(kv[0][1],kv[0][0])):
  p=bytearray((x,y))
  for cid in stack:p+=u8(A_ITEM)+u16(c2s[cid])
  kids.append(node(TILE_NODE,bytes(p)))
 return node(AREA,struct.pack("<HHB",BASE_X,BASE_Y,z),kids)
def inspect(payload,s2c):
 root,end=parse_node(payload,4)
 if end!=len(payload):raise RuntimeError("OTBM parse end")
 mapsn=[x for x in root.children if x.node_type==MAP]
 out={}
 for ar in mapsn[0].children:
  if ar.node_type!=AREA:continue
  bx,by,bz=struct.unpack_from("<HHB",ar.props,0)
  for t in ar.children:
   lx,ly=t.props[:2];off=2;stack=[]
   while off<len(t.props):
    if t.props[off]!=A_ITEM:raise RuntimeError("tile attr")
    sid=struct.unpack_from("<H",t.props,off+1)[0];off+=3;stack.append(s2c[sid])
   out[(bx+lx,by+ly,bz)]=stack
 return out
def project(p,c):
 x,y,z=p;cx,cy,cz=c;return ((x-cx)-(cz-z),(y-cy)-(cz-z))

def build():
 lower={(x,y):[GROUND] for y in range(SCENE_H) for x in range(SCENE_W)}
 topo=boundary();roles={}
 ox,oy=ORIGIN
 east_mid=(ox+2,oy+1)
 south_left=(ox,oy+2)
 south_mid=(ox+1,oy+2)
 southeast=(ox+2,oy+2)
 for pos in sorted(topo,key=lambda p:(p[1],p[0])):
  role=HALF[cardinal(topo,*pos)]
  cid=BASE_WALL[role];semantic=f"structural_{role}"
  # User's visible east facade: cells 4/8/12.
  if pos[0]==ox+2 and pos!=southeast:
   if pos==east_mid:
    cid=FACADE["east_window"];semantic="east_window"
   else:
    cid=FACADE["east_wall"];semantic="east_timber_wall"
  # User's visible south facade: cells 13/14/15/16.
  if pos[1]==oy+2:
   if pos==south_left:
    cid=FACADE["south_window"];semantic="south_window"
   elif pos==south_mid:
    cid=FACADE["south_door"];semantic="south_door"
   elif pos==southeast:
    cid=FACADE["south_east_corner"];semantic="south_east_corner"
   else:
    cid=FACADE["south_wall"];semantic="south_timber_wall"
  lower[pos].append(cid);roles[pos]=semantic
 upper={(ox+lx+1,oy+ly):[cid] for (lx,ly),cid in ROOF.items()}
 return lower,upper,roles

def emit(lower,upper,c2s):
 props=u8(A_DESC)+s("PP-MAP one house v3 cream timber band facade")
 rp=struct.pack("<IHHII",2,65535,65535,3,55)
 return IDENT+node(ROOT,rp,(node(MAP,props,(area(LOWER_Z,lower,c2s),area(UPPER_Z,upper,c2s))),))

def render(pos,items,sprites,path,crop=False):
 W,H=(300,280) if crop else (620,470)
 im=Image.new("RGBA",(W,H),(22,24,28,255));d=ImageDraw.Draw(im);font=ImageFont.load_default()
 if not crop:
  d.text((8,8),"ONE HOUSE V3 — map creator / exact current sprites",fill=(240,240,240,255),font=font)
  d.text((8,25),"red positional roof + cream wall + timber-band facade",fill=(185,192,202,255),font=font)
  base=(250,175)
 else:
  base=(90,70)
 cam=(BASE_X+ORIGIN[0],BASE_Y+ORIGIN[1],LOWER_Z)
 for z in (LOWER_Z,UPPER_Z):
  for (x,y,zz),stack in sorted(((p,s) for p,s in pos.items() if p[2]==z),key=lambda kv:(kv[0][1],kv[0][0])):
   sx,sy=project((x,y,zz),cam)
   for cid in stack:
    obj=render_item_thing(items[cid],sprites)
    im.alpha_composite(obj,(base[0]+sx*TILE+TILE-obj.width,base[1]+sy*TILE+TILE-obj.height))
 path.parent.mkdir(parents=True,exist_ok=True);im.convert("RGB").save(path,optimize=True)

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--otsp",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
 a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 req={GROUND,*ROOF.values(),*BASE_WALL.values(),*FACADE.values()}
 c2s,s2c=maps(a.otsp,req)
 lower,upper,roles=build();payload=emit(lower,upper,c2s);pos=inspect(payload,s2c)
 pl={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==LOWER_Z}
 pu={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==UPPER_Z}
 if pl!=lower or pu!=upper:raise RuntimeError("exact parseback mismatch")
 otbm=a.out/"one_house_v3.otbm";otbm.write_bytes(payload)
 _,items=parse_all_items(a.otsp/"client_files"/"otsp.dat");sprites=_Sprites(a.otsp/"client_files"/"otsp.spr")
 render(pos,items,sprites,a.out/"one_house_v3.png",False)
 render(pos,items,sprites,a.out/"one_house_v3_close.png",True)
 report={
  "result":"PASS","proof_key":"ONE_HOUSE_V3_CREAM_TIMBER_BAND",
  "scope":"ONE_HOUSE_ONLY",
  "roof_matrix":[[902,907,901],[903,908,904],[909,905,906]],
  "base_wall":BASE_WALL,"facade":FACADE,
  "roles":{f"{x},{y}":v for (x,y),v in roles.items()},
  "world_delta":list(WORLD_DELTA),
  "otbm":{"file":otbm.name,"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),"exact_parseback":True},
  "render":{"file":"one_house_v3.png","close":"one_house_v3_close.png","exact_current_dat_spr":True,"image_generation_used":False},
  "production_status":"UNCLASSIFIED"
 }
 (a.out/"one_house_v3.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__":main()
