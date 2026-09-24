#!/usr/bin/env python3
"""Render one-house wall-family candidates under the same exact roof."""
from __future__ import annotations
import argparse, json, math, struct
from pathlib import Path
from typing import Iterable
from PIL import Image, ImageDraw, ImageFont
from build_pp_map_001_lab import TILE, _Sprites, parse_all_items, render_item_thing
from extract_otb_item_client_ids import extract_records, parse_node

IDENT=b"OTBM";NS=0xFE;NE=0xFF;ESC=0xFD
ROOT=1;MAP=2;AREA=4;TILE_NODE=5;A_DESC=1;A_ITEM=9
BASE_X=34000;BASE_Y=34000;LOWER_Z=7;UPPER_Z=6;GROUND=101
ORIGIN=(4,4);SCENE_W=11;SCENE_H=10;WORLD_DELTA=(1,0,-1)
ROOF={(0,0):902,(1,0):907,(2,0):901,(0,1):903,(1,1):908,(2,1):904,(0,2):909,(1,2):905,(2,2):906}
HALF={0:"pole",1:"vertical",2:"horizontal",3:"corner",4:"pole",5:"vertical",6:"horizontal",7:"corner",8:"pole",9:"vertical",10:"horizontal",11:"corner",12:"pole",13:"vertical",14:"horizontal",15:"corner"}

# Each family is a complete current-asset set: vertical,horizontal,pole,corner,
# vertical-window,horizontal-window,vertical-opening,horizontal-opening.
FAMILIES={
 "cream_plain_778":{
   "wall":{"vertical":778,"horizontal":779,"pole":780,"corner":781},
   "window":{"vertical":782,"horizontal":784},
   "opening":{"vertical":783,"horizontal":785},
 },
 "cream_base_786":{
   "wall":{"vertical":786,"horizontal":787,"pole":788,"corner":789},
   "window":{"vertical":790,"horizontal":792},
   "opening":{"vertical":791,"horizontal":793},
 },
 "cream_timber_651":{
   "wall":{"vertical":651,"horizontal":652,"pole":653,"corner":657},
   "window":{"vertical":654,"horizontal":655},
   "opening":{"vertical":658,"horizontal":659},
 },
 "cream_timber_633":{
   "wall":{"vertical":633,"horizontal":636,"pole":639,"corner":642},
   "window":{"vertical":634,"horizontal":637},
   "opening":{"vertical":635,"horizontal":638},
 },
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
  if len(ms)!=1:raise RuntimeError(f"{cid}: {ms}")
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
 mapsn=[x for x in root.children if x.node_type==MAP];out={}
 for ar in mapsn[0].children:
  if ar.node_type!=AREA:continue
  bx,by,bz=struct.unpack_from("<HHB",ar.props,0)
  for t in ar.children:
   lx,ly=t.props[:2];off=2;stack=[]
   while off<len(t.props):
    sid=struct.unpack_from("<H",t.props,off+1)[0];off+=3;stack.append(s2c[sid])
   out[(bx+lx,by+ly,bz)]=stack
 return out
def project(p,c):
 x,y,z=p;cx,cy,cz=c;return ((x-cx)-(cz-z),(y-cy)-(cz-z))
def build(fam):
 lower={(x,y):[GROUND] for y in range(SCENE_H) for x in range(SCENE_W)}
 topo=boundary();f=FAMILIES[fam]
 # Put a window mid-east, a window west-south, and an opening south-center.
 east_win=(ORIGIN[0]+2,ORIGIN[1]+1)
 south_win=(ORIGIN[0],ORIGIN[1]+2)
 south_open=(ORIGIN[0]+1,ORIGIN[1]+2)
 roles={}
 for pos in sorted(topo,key=lambda p:(p[1],p[0])):
  role=HALF[cardinal(topo,*pos)]
  cid=f["wall"][role];semantic=role
  if pos==east_win:
   cid=f["window"]["vertical"];semantic="east_window"
  elif pos==south_win:
   cid=f["window"]["vertical"];semantic="south_window"
  elif pos==south_open:
   cid=f["opening"]["horizontal"];semantic="south_door/opening"
  lower[pos].append(cid);roles[pos]=semantic
 upper={(ORIGIN[0]+lx+1,ORIGIN[1]+ly):[cid] for (lx,ly),cid in ROOF.items()}
 return lower,upper,roles
def emit(lower,upper,c2s,label):
 props=u8(A_DESC)+s(label);rp=struct.pack("<IHHII",2,65535,65535,3,55)
 return IDENT+node(ROOT,rp,(node(MAP,props,(area(LOWER_Z,lower,c2s),area(UPPER_Z,upper,c2s))),))
def render(pos,items,sprites,label):
 im=Image.new("RGBA",(470,390),(22,24,28,255));d=ImageDraw.Draw(im);font=ImageFont.load_default()
 d.text((8,8),label,fill=(240,240,240,255),font=font)
 cam=(BASE_X+ORIGIN[0],BASE_Y+ORIGIN[1],LOWER_Z);base=(175,125)
 for z in (LOWER_Z,UPPER_Z):
  for (x,y,zz),stack in sorted(((p,s) for p,s in pos.items() if p[2]==z),key=lambda kv:(kv[0][1],kv[0][0])):
   sx,sy=project((x,y,zz),cam)
   for cid in stack:
    obj=render_item_thing(items[cid],sprites)
    im.alpha_composite(obj,(base[0]+sx*TILE+TILE-obj.width,base[1]+sy*TILE+TILE-obj.height))
 return im
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--otsp",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
 a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 req={GROUND,*ROOF.values()}
 for f in FAMILIES.values():
  req|=set(f["wall"].values())|set(f["window"].values())|set(f["opening"].values())
 c2s,s2c=maps(a.otsp,req)
 _,items=parse_all_items(a.otsp/"client_files"/"otsp.dat");sprites=_Sprites(a.otsp/"client_files"/"otsp.spr")
 rows=[];report={}
 for name in FAMILIES:
  lower,upper,roles=build(name);payload=emit(lower,upper,c2s,name);pos=inspect(payload,s2c)
  pl={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==LOWER_Z}
  pu={(x-BASE_X,y-BASE_Y):st for (x,y,z),st in pos.items() if z==UPPER_Z}
  if pl!=lower or pu!=upper:raise RuntimeError(f"{name} parseback")
  (a.out/f"{name}.otbm").write_bytes(payload)
  img=render(pos,items,sprites,name);img.convert("RGB").save(a.out/f"{name}.png",optimize=True)
  rows.append((name,img))
  report[name]={"roles":{f"{x},{y}":v for (x,y),v in roles.items()},"otbm":f"{name}.otbm","render":f"{name}.png"}
 # montage
 out=Image.new("RGB",(940,780),(18,20,24))
 for i,(name,img) in enumerate(rows):
  out.paste(img.convert("RGB"),((i%2)*470,(i//2)*390))
 out.save(a.out/"house_family_candidates.png",optimize=True)
 (a.out/"house_family_candidates.json").write_text(json.dumps({"result":"PASS","families":report},indent=2)+"\n")
 print("PASS",list(FAMILIES))
if __name__=="__main__":main()
