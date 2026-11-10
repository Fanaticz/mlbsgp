#!/usr/bin/env python3
"""Does adding a leg from another game move Novig's price on a Points + Threes play?

  python3 third_leg.py "Klay Thompson" 13.5 3.5 [how many legs to try, default 150]

Quotes the two-leg slip, then the same slip with each of ~150 tight main-line
legs from other games (tennis, NHL, NBA, NFL, college, UFC, soccer), with the
added leg's own Novig price as its fair value. Prints the best and worst and
what the added leg cost by league, market type, price and time to start.
First run (11-10, overnight): every leg cost EV; same-day legs about 11-13%,
legs more than two days out about 31%, spreads twice moneylines and totals.
"""
import sys, json, math, collections, concurrent.futures, urllib.request, urllib.parse, random, time
import os
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,"..","nba-ast-pts-sgp"))
import novig, sgp, scan, price
PLAYER, PL, TL = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
d,by=sgp.load(); ms=novig.fetch(stats=("pts","tpm")); nm,rows=novig.ladder(ms,PLAYER)
P=next(r for r in rows["pts"] if r["line"]==PL); T=next(r for r in rows["tpm"] if r["line"]==TL)
r=price.shrunk_r(d,by,by[PLAYER],"pts","tpm")[0]; j=sgp.joint(r,P["fo"],T["fo"]); base=[P["ids"]["over"],T["ids"]["over"]]
ev_id=next(m["eventId"] for m in ms if novig.player_name(m)==nm)
q2s=[]
for _ in range(3): q,_w=novig.parlay(base); q2s.append(q); time.sleep(1.2)
q2=q2s[-1]; print(f"{nm} {int(PL+.5)}+ PTS · {int(TL+.5)}+ 3PM: fair {1/j:.2f}x · two-leg quotes {q2s} -> slip {novig.slip_multiplier(q2):.2f}x EV {j*novig.slip_multiplier(q2)-1:+.1%}")
def cat(lg, types):
    q={"league":lg,"eventStatus":"OPEN_PREGAME","limit":5000,"marketType":types}
    req=urllib.request.Request(f"{novig.HOST}/v3/public/catalog/markets?{urllib.parse.urlencode(q)}",headers={"Accept":"application/json","User-Agent":"nba-sgp-fv"})
    try: return json.load(urllib.request.urlopen(req,timeout=30)).get("items",[])
    except Exception as e: return []
legs=[]
for lg in ("ATP","WTA","NBA","NHL","NFL","NCAAB","NCAAF","NCAAWB","UFC","MLS","UEFA Nations League","Liga MX","League of Legends","Counter Strike 2","Dota 2","PGA","Boxing"):
    it=cat(lg,"MONEY,SPREAD,TOTAL,MONEYLINE_3_WAY_WIN")
    best={}
    for m in it:
        if m["eventId"]==ev_id: continue
        o=m["outcomes"]
        if len(o)!=2 or not all(x.get("bid") for x in o): continue
        b0,b1=float(o[0]["bid"]["price"]),float(o[1]["bid"]["price"]); sp=1-b1-b0
        if not 0<b0<1-b1<1 or sp>0.03: continue
        f=sgp.devig_worst(1-b1,1-b0)
        k=(m["eventId"],m["marketType"])
        cand=dict(lg=lg,type=m["marketType"],desc=m["description"],starts=m["startsTs"],sp=sp,f=f,ids=[x["outcomeId"] for x in o],names=[x["name"] for x in o],vol=m.get("volume") or 0)
        if k not in best or abs(f[0]-.5)<abs(best[k]["f"][0]-.5): best[k]=cand
    v=list(best.values()); random.seed(4); random.shuffle(v)
    per=collections.Counter(); 
    for c in v:
        if per[c["type"]]<(8 if lg in ("ATP","WTA") else 4): per[c["type"]]+=1; legs.append(c)
    print(f"  {lg}: {len(it)} markets, {len(best)} tight main lines, using {sum(per.values())}")
todo=[]
for c in legs:
    for i in (0,1):
        if 0.25<=c["f"][i]<=0.80: todo.append(dict(c,i=i,p=c["f"][i],name=c["names"][i]))
random.shuffle(todo); todo=todo[:int(sys.argv[4]) if len(sys.argv)>4 else 150]
print(len(todo),"third legs to try")
pace=scan.Pace()
def one(c): pace.wait(); c["q"],c["why"]=novig.parlay(base+[c["ids"][c["i"]]])
with concurrent.futures.ThreadPoolExecutor(3) as ex: list(ex.map(one,todo))
q2e,_=novig.parlay(base); print("two-leg quote at end:",q2e)
ok=[c for c in todo if c["q"]]
print("fails:",collections.Counter(c["why"] for c in todo if not c["q"]).most_common(4))
for c in ok:
    c["slip"]=novig.slip_multiplier(c["q"]); c["ev"]=j*c["p"]*c["slip"]-1
    c["legprice"]=c["q"]/q2          # what Novig charged for the added leg
    c["boost"]=c["p"]/c["legprice"]-1  # >0: the leg came cheaper than its own fair price
    c["hrs"]=(c["starts"]/1000-time.time())/3600
ev2=j*novig.slip_multiplier(q2)-1
print(f"\nbaseline two-leg EV {ev2:+.1%}. Top 15 third legs by EV:")
for c in sorted(ok,key=lambda c:-c["ev"])[:15]:
    print(f"  {c['lg']:8} {c['type']:7} {c['desc'][:30]:30} {c['name'][:14]:14} fair {sgp.american(c['p']):+5d} · leg priced at {sgp.american(min(c['legprice'],.999)):+5d} ({c['boost']:+.1%}) · slip {c['slip']:.2f}x EV {c['ev']:+.1%} · starts in {c['hrs']:.0f}h · book {c['sp']*100:.1f}c vol {c['vol']}")
print("bottom 5:")
for c in sorted(ok,key=lambda c:c["ev"])[:5]:
    print(f"  {c['lg']:8} {c['type']:7} {c['desc'][:30]:30} {c['name'][:14]:14} fair {sgp.american(c['p']):+5d} · leg priced at {sgp.american(min(c['legprice'],.999)):+5d} ({c['boost']:+.1%}) · EV {c['ev']:+.1%}")
def grp(key,label):
    g=collections.defaultdict(list)
    for c in ok: g[key(c)].append(c["boost"])
    print(f"\nadded-leg discount by {label} (positive = leg came cheaper than fair):")
    for k,v in sorted(g.items(),key=lambda kv:-sorted(kv[1])[len(kv[1])//2]):
        v.sort(); print(f"  {str(k):22} n{len(v):3} median {v[len(v)//2]:+.1%}  best {v[-1]:+.1%}  worst {v[0]:+.1%}")
grp(lambda c:c["lg"],"league"); grp(lambda c:c["type"],"market type")
grp(lambda c:"fav 60%+" if c["p"]>=.6 else "dog <40%" if c["p"]<.4 else "near even","leg price")
grp(lambda c:"<12h" if c["hrs"]<12 else "12-48h" if c["hrs"]<48 else "2d+","time to start")
