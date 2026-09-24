#!/usr/bin/env python3
"""One house v6: brown shingle roof matching the user's Minibia reference."""
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
ORIGIN=(5,5);SCENE_W=16;SCENE_H=14;WORLD_DELTA=(0,0,-1);W=5;H=4

ROOF_NORTH=189
ROOF_FILL=190
ROOF_SOUTH_EDGE=508

BASE_WALL={"vertical":651,"horizontal":652,"pole":653,"corner":657}
FACADE={"east_wall":661,"east_window":663,"south_wall":662,"south_window":664,"south_door":668,"se_corner":660}
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
 for x in range(W):pts.add((ox+x,oy));pts.add((ox+x,oy+H-1))
 for y in range(H):pts.add((ox,oy+y));pts.add((ox+W-1,oy+y))
 return pts
def maps(otsp,ids):
 recs=extract_records(otsp/"server_files"/"items.otb");bc={}
 for sid,r in recs.items():bc.setdefault(int(r["client_id"]),[]).append(int(sid))
 c2s={}
 for cid in sorted(ids):
  ms=bc.get(cid,[])
  if len(ms)!=1:raise RuntimeError(f"client {cid}: {ms}")
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
 if end!=len(payload):raise RuntimeError("parse end")
 out={};mapsn=[x for x in root.children if x.node_type==MAP]
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

def build_lower():
 lower={(x,y):[GROUND] for y in range(SCENE_H) for x in range(SCENE_W)}
 topo=boundary();roles={};ox,oy=ORIGIN

 east_windows={(ox+W-1,oy+1),(ox+W-1,oy+2)}
 south_y=oy+H-1
 south_windows={(ox,south_y),(ox+3,south_y)}
 south_door=(ox+2,south_y)
 se=(ox+W-1,south_y)

 for pos in sorted(topo,key=lambda p:(p[1],p[0])):
  role=HALF[cardinal(topo,*pos)]
  cid=BASE_WALL[role];sem=f"structural_{role}"

  if pos[0]==ox+W-1 and pos!=se:
   if pos in east_windows:
    cid=FACADE["east_window"];sem="east_window"
   else:
    cid=FACADE["east_wall"];sem="east_timber_wall"

  if pos[1]==south_y:
   if pos in south_windows:
    cid=FACADE["south_window"];sem="south_window"
   elif pos==south_door:
    cid=FACADE["south_door"];sem="south_door"
   elif pos==se:
    cid=FACADE["se_corner"];sem="south_east_corner"
   else:
    cid=FACADE["south_wall"];sem="south_timber_wall"

  lower[pos].append(cid);roles[pos]=sem
 return lower,roles

def build_upper():
 ox,oy=ORIGIN;rx=ox;ry=oy
 upper={};roles={}
 for y in range(H):
  for x in range(W):
   if y==0:
    stack=[ROOF_NORTH];role="north_edge"
   elif y==H-1:
    stack=[ROOF_FILL,ROOF_SOUTH_EDGE];role="south_edge"
   else:
    stack=[ROOF_FILL];role="fill"
   upper[(rx+x,ry+y)]=stack
   roles[(x,y)]={"role":role,"stack":stack}
 return upper,roles

def emit(lower,upper,c2s):
 props=u8(A_DESC)+s("PP-MAP one bigger house v8 5x4")
 rp=struct.pack("<IHHII",2,65535,65535,3,55)
 return IDENT+node(ROOT,rp,(node(MAP,props,(area(LOWER_Z,lower,c2s),area(UPPER_Z,upper,c2s))),))

def render(pos,items,sprites,path,close=False):
 Wpx,Hpx=(360,300) if close else (640,480)
 im=Image.new("RGBA",(Wpx,Hpx),(22,24,28,255));d=ImageDraw.Draw(im);font=ImageFont.load_default()
 if not close:
  d.text((8,8),"ONE BIGGER HOUSE V8 — 5x4, V7 alignment preserved",fill=(240,240,240,255),font=font)
  d.text((8,25),"approved V7 alignment preserved; footprint expanded to 5x4",fill=(185,192,202,255),font=font)
  base=(255,175)
 else:base=(115,85)
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
 req={GROUND,ROOF_NORTH,ROOF_FILL,ROOF_SOUTH_EDGE,*BASE_WALL.values(),*FACADE.values()}
 c2s,s2c=maps(a.otsp,req)
 lower,wallroles=build_lower();upper,roofroles=build_upper();payload=emit(lower,upper,c2s);pos=inspect(payload,s2c)
 pl={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==LOWER_Z}
 pu={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==UPPER_Z}
 if pl!=lower or pu!=upper:raise RuntimeError("parseback mismatch")
 if any(cid>=901 and cid<=918 for st in upper.values() for cid in st):raise RuntimeError("macro roof present")
 otbm=a.out/"one_house_v8_big.otbm";otbm.write_bytes(payload)
 _,items=parse_all_items(a.otsp/"client_files"/"otsp.dat");sprites=_Sprites(a.otsp/"client_files"/"otsp.spr")
 render(pos,items,sprites,a.out/"one_house_v8_big.png",False)
 render(pos,items,sprites,a.out/"one_house_v8_big_close.png",True)
 report={
  "result":"PASS","proof_key":"ONE_HOUSE_V8_BIG_5X4",
  "scope":"ONE_BIGGER_HOUSE_ONLY","parent_user_approved_baseline":"ONE_HOUSE_V7_ROOF_SHIFTED_LEFT","footprint":{"width":W,"height":H},"roof_alignment":{"x_delta_from_wall_origin":0,"y_delta_from_wall_origin":0,"z_delta":-1},"macro_roof_901_918_used":False,
  "roof":{"north":ROOF_NORTH,"fill":ROOF_FILL,"south_edge":ROOF_SOUTH_EDGE,"roles":{f"{x},{y}":v for (x,y),v in roofroles.items()}},
  "wall":BASE_WALL,"facade":FACADE,"wall_roles":{f"{x},{y}":v for (x,y),v in wallroles.items()},
  "otbm":{"file":otbm.name,"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),"exact_parseback":True},
  "render":{"file":"one_house_v8_big.png","close":"one_house_v8_big_close.png","exact_current_dat_spr":True,"image_generation_used":False},
  "production_status":"UNCLASSIFIED"
 }
 (a.out/"one_house_v8_big.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__":main()
