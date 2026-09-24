#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, struct
from collections import Counter, deque
from pathlib import Path

NS=0xFE; NE=0xFF; ESC=0xFD; ROOT=1; MAP=2; AREA=4; TILE_NODE=5; A_ITEM=9
BASE_X=34600; BASE_Y=34600; OUTPUT_AREA_X=34560; OUTPUT_AREA_Y=34560; LOWER_Z=7; UPPER_Z=6
GRASS={101,102,103,104,105}
EXPECTED_BASE_SHA='93b3da81bc799404a0d81d0d9b09b754c676c0f646c6e07eb7e3b2259758150d'
EXPECTED_MODULE_SHA='20ec5cb88db4b19c7b7d25e47f7e6102073d9dd3cac8643bfbd0a7039bbd95e2'
EXPECTED_OUT_SHA='209f82e6e8b2829c0aa98fa351a870ab024a5fcfddca04758623b299e11a9677'

class Node:
    def __init__(self,t,p,c): self.node_type=t; self.props=p; self.children=c

def parse_node(data,off):
    if data[off]!=NS: raise RuntimeError(f'expected node start at {off}')
    t=data[off+1]; off+=2; props=bytearray(); children=[]
    while off<len(data):
        b=data[off]
        if b==ESC: props.append(data[off+1]); off+=2
        elif b==NS:
            child,off=parse_node(data,off); children.append(child)
        elif b==NE: return Node(t,bytes(props),children),off+1
        else: props.append(b); off+=1
    raise RuntimeError('unterminated node')

def esc(data):
    out=bytearray()
    for b in data:
        if b in (NS,NE,ESC): out.append(ESC)
        out.append(b)
    return bytes(out)

def node(t,props=b'',children=()): return bytes((NS,t))+esc(props)+b''.join(children)+bytes((NE,))

def parse_otbm(path):
    payload=Path(path).read_bytes()
    if not payload.startswith(b'OTBM'): raise RuntimeError('not OTBM')
    root,end=parse_node(payload,4)
    if end!=len(payload): raise RuntimeError('trailing bytes')
    maps=[c for c in root.children if c.node_type==MAP]
    if len(maps)!=1: raise RuntimeError('expected one map node')
    m=maps[0]; tiles={}
    for area in m.children:
        if area.node_type!=AREA: continue
        bx,by,z=struct.unpack_from('<HHB',area.props,0)
        for tile in area.children:
            if tile.node_type!=TILE_NODE or tile.children: raise RuntimeError('unsupported tile node')
            lx,ly=tile.props[:2]; off=2; stack=[]
            while off<len(tile.props):
                if tile.props[off]!=A_ITEM: raise RuntimeError('unsupported tile attribute')
                stack.append(struct.unpack_from('<H',tile.props,off+1)[0]); off+=3
            tiles[(bx+lx,by+ly,z)]=stack
    return {'payload':payload,'root_props':root.props,'map_props':m.props,'tiles':tiles}

def build_otbm(root_props,map_props,tiles):
    areas=[]
    for z in sorted({p[2] for p in tiles},reverse=True):
        tnodes=[]
        for (x,y,zz),stack in sorted(((p,s) for p,s in tiles.items() if p[2]==z),key=lambda kv:(kv[0][1],kv[0][0])):
            lx,ly=x-OUTPUT_AREA_X,y-OUTPUT_AREA_Y
            if not(0<=lx<=255 and 0<=ly<=255): raise RuntimeError('coordinate outside area byte range')
            props=bytearray((lx,ly))
            for sid in stack: props += bytes((A_ITEM,))+struct.pack('<H',sid)
            tnodes.append(node(TILE_NODE,bytes(props)))
        areas.append(node(AREA,struct.pack('<HHB',OUTPUT_AREA_X,OUTPUT_AREA_Y,z),tnodes))
    return b'OTBM'+node(ROOT,root_props,[node(MAP,map_props,areas)])

def reachable(domain,blocked,start,goal):
    allowed=set(domain)|{start,goal}; q=deque([start]); seen={start}
    while q:
        p=q.popleft()
        if p==goal:return True
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            n=(p[0]+dx,p[1]+dy)
            if n in allowed and n not in blocked and n not in seen:
                seen.add(n); q.append(n)
    return False

def main():
    root=Path(__file__).resolve().parents[1]
    base=parse_otbm(root/'fixtures'/'dogleg_base.otbm')
    module=parse_otbm(root/'fixtures'/'exact_3x3_house.otbm')
    if hashlib.sha256(base['payload']).hexdigest()!=EXPECTED_BASE_SHA: raise RuntimeError('base fixture drift')
    if hashlib.sha256(module['payload']).hexdigest()!=EXPECTED_MODULE_SHA: raise RuntimeError('module fixture drift')

    module_lower=[(p,s) for p,s in module['tiles'].items() if p[2]==LOWER_Z and len(s)>1]
    module_upper=[(p,s) for p,s in module['tiles'].items() if p[2]==UPPER_Z]
    if len(module_lower)!=8 or len(module_upper)!=9: raise RuntimeError('accepted 3x3 module shape drift')
    sx=min(p[0] for p,s in module_lower); sy=min(p[1] for p,s in module_lower)
    lower_template={(p[0]-sx,p[1]-sy):s[1:] for p,s in module_lower}
    upper_template={(p[0]-sx,p[1]-sy):s for p,s in module_upper}

    host_lower={(BASE_X+x,BASE_Y+y,LOWER_Z) for y in range(2,11) for x in range(3,10)}
    host_upper={(BASE_X+x,BASE_Y+y,UPPER_Z) for y in range(3,12) for x in range(4,11)}
    module_origins=((3,3),(7,3)); route_approach=(6,11); module_approaches=((4,6),(8,6))

    out={p:list(s) for p,s in base['tiles'].items()}
    before=Counter()
    for p in host_lower:
        stack=out[p]
        if not stack or stack[0] not in GRASS: raise RuntimeError(f'host foundation drift {p} {stack}')
        before[str(stack[0])]+=1
        out[p]=[stack[0]]
    for p in host_upper:
        if p not in out: raise RuntimeError(f'host roof tile missing {p}')
        del out[p]

    structural=set(); roofs=set()
    for mx,my in module_origins:
        for (dx,dy),extra in lower_template.items():
            local=(mx+dx,my+dy); p=(BASE_X+local[0],BASE_Y+local[1],LOWER_Z)
            if p not in host_lower: raise RuntimeError('module escaped lower envelope')
            out[p]=[out[p][0],*extra]; structural.add(local)
        for (dx,dy),stack in upper_template.items():
            local=(mx+dx,my+dy); p=(BASE_X+local[0],BASE_Y+local[1],UPPER_Z)
            if p not in host_upper: raise RuntimeError('module escaped upper envelope')
            if local in roofs: raise RuntimeError('module roof overlap')
            out[p]=list(stack); roofs.add(local)

    after=Counter(str(out[p][0]) for p in host_lower)
    if before!=after: raise RuntimeError('host grass variants changed')
    expected_hist={'101':31,'102':10,'103':10,'104':5,'105':7}
    if dict(sorted(before.items()))!=expected_hist: raise RuntimeError(f'ground histogram drift {before}')
    changed=[p for p in set(base['tiles'])|set(out) if base['tiles'].get(p)!=out.get(p)]
    outside=[p for p in changed if p not in host_lower and p not in host_upper]
    if outside: raise RuntimeError(f'edit escaped host envelope: {outside[:5]}')
    if len(changed)!=101: raise RuntimeError(f'changed-tile count drift {len(changed)}')
    domain={(x,y) for y in range(2,11) for x in range(3,10)}
    if not all(reachable(domain,structural,route_approach,g) for g in module_approaches): raise RuntimeError('court reachability failed')
    route_pos=(BASE_X+route_approach[0],BASE_Y+route_approach[1],LOWER_Z)
    if out.get(route_pos)!=base['tiles'].get(route_pos): raise RuntimeError('route approach mutated')

    payload=build_otbm(base['root_props'],base['map_props'],out)
    sha=hashlib.sha256(payload).hexdigest()
    if sha!=EXPECTED_OUT_SHA or len(payload)!=12476 or len(out)!=1435: raise RuntimeError(f'compound output drift {len(payload)} {len(out)} {sha}')
    outdir=root/'out'; outdir.mkdir(exist_ok=True)
    outpath=outdir/'woodland_dogleg_north_lodge_twin_fixed3x3_compound_v1.otbm'; outpath.write_bytes(payload)
    parsed=parse_otbm(outpath)
    if parsed['tiles']!=out: raise RuntimeError('compound exact parseback failed')
    report={
      'result':'PASS','proof':'PP-MAP-PUBLIC-COMPOUND-SMOKE-V1',
      'base_sha256':EXPECTED_BASE_SHA,'module_sha256':EXPECTED_MODULE_SHA,
      'output_sha256':sha,'output_bytes':len(payload),'output_tile_count':len(out),
      'changed_tile_count':len(changed),'outside_host_envelope_changes':0,
      'ground_variant_histogram':dict(sorted(before.items())),
      'route_approach':list(route_approach),'module_approaches':[list(x) for x in module_approaches],
      'module_origins':[list(x) for x in module_origins],
      'exact_parseback':True,'fixed_module_resized':False,'fixed_roofs_joined':False,
    }
    (outdir/'proof.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=='__main__': main()
