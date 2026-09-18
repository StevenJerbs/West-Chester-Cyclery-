# Fits a lower-link-driven VPP four-bar (Bullit-style) to published outputs: 170 mm rear travel
# over a 230x65 shock, leverage ratio ~3.0 -> ~2.4, a Megatower-style axle path (~2 mm rearward
# to sag, then forward), the axle at chainstay 449 mm with a 27.5" rear wheel, and soft priors
# placing the lower-link pivot behind the BB, the upper pivot on the seat tube and the shock
# running up-forward into the front triangle as in the Pinkbike photos. Prints the layout that
# suspension-lab.html embeds as VPP = {...}. Needs numpy + scipy.
import numpy as np
from scipy.optimize import minimize
AX0=np.array([-0.449,0.006]); E2E=0.230; STROKE=0.065
def solve(p, n=120, sweep=2.2):
    P1=np.array(p[0:2]); L1=p[2]; P3=np.array(p[3:5]); L2=p[5]; D=p[6]
    ax_loc=np.array(p[7:9]); S_loc=np.array(p[9:11]); F=np.array(p[11:13]); th0=p[13]; sgn=p[14]; br=p[15]
    prevP4=None; rows=[]
    for s in np.linspace(0,sweep,n):
        th=th0+sgn*s
        P2=P1+L1*np.array([np.cos(th),np.sin(th)]); v=P3-P2; d=np.linalg.norm(v)
        if d>L2+D or d<abs(L2-D): break
        a=(D**2-L2**2+d**2)/(2*d); h=np.sqrt(max(0,D**2-a**2)); m=P2+a*v/d; perp=np.array([-v[1],v[0]])/d
        c1=m+h*perp; c2=m-h*perp
        if prevP4 is None: P4=c1 if br>0 else c2
        else: P4=c1 if np.linalg.norm(c1-prevP4)<np.linalg.norm(c2-prevP4) else c2
        prevP4=P4; ex=(P4-P2)/D; ey=np.array([-ex[1],ex[0]]); axle=P2+ax_loc[0]*ex+ax_loc[1]*ey
        lx=(P2-P1)/L1; ly=np.array([-lx[1],lx[0]]); S=P1+S_loc[0]*lx+S_loc[1]*ly
        rows.append((th,axle,np.linalg.norm(S-F),P2,P4,S))
    return rows
def metrics(p):
    r=solve(p)
    if len(r)<10: return None
    ax=np.array([o[1] for o in r]); sl=np.array([o[2] for o in r])
    stroke=sl[0]-sl; trav=ax[:,1]-ax[0,1]
    if np.any(np.diff(stroke)<=1e-7) or stroke[-1]<STROKE: return None
    if np.any(np.diff(trav)<=0): return None
    i=int(np.searchsorted(stroke,STROKE))
    lr=np.gradient(trav,stroke)
    return dict(travel=float(np.interp(STROKE,stroke,trav)),lr0=float(lr[0]),lr65=float(np.interp(STROKE,stroke,lr)),
                e2e=float(sl[0]),axle0=ax[0],lr=lr[:i+1],stroke=stroke[:i+1],trav=trav[:i+1],raw=r[:i+1],
                xshift=float(ax[i,0]-ax[0,0]))
def axlepath(m):
    # Megatower-style: ~2 mm rearward to sag (45 mm), then forward, ending 5-15 mm forward of start
    r=m['raw']; x0=r[0][1][0]; c=0.0
    xs=np.array([o[1][0] for o in r]); ts=np.array([o[1][1]-r[0][1][1] for o in r])
    x45=np.interp(0.045,ts,xs)-x0; xe=xs[-1]-x0
    c+=max(0,-0.004-x45)**2*3e5 + max(0,x45-0.0)**2*3e5
    c+=max(0,0.004-xe)**2*2e5 + max(0,xe-0.015)**2*2e5
    return c
def layout(p):
    P1=np.array(p[0:2]); P3=np.array(p[3:5]); F=np.array(p[11:13])
    c=np.sum((P1-np.array([-0.03,0.06]))**2)*40 + np.sum((P3-np.array([-0.09,0.29]))**2)*40 + np.sum((F-np.array([0.11,0.30]))**2)*40
    return c
def cost(p):
    m=metrics(p)
    if m is None: return 1e3
    c=layout(p)
    c+=(m['travel']-0.170)**2*4e4 + (m["lr0"]-3.00)**2*3 + (m["lr65"]-2.30)**2*3 + (m['e2e']-E2E)**2*4e4
    c+=np.linalg.norm(m['axle0']-AX0)**2*4e3
    c+=np.sum(np.clip(np.diff(m['lr']),0,None)**2)*30
    c+=axlepath(m)
    return c
def build(rng):
    P1=np.array([rng.uniform(-0.08,0.02),rng.uniform(0.0,0.11)]); L1=rng.uniform(0.04,0.10); th0=rng.uniform(0,2*np.pi)
    P2=P1+L1*np.array([np.cos(th0),np.sin(th0)])
    P3=np.array([rng.uniform(-0.14,-0.03),rng.uniform(0.22,0.34)]); L2=rng.uniform(0.05,0.13); a2=rng.uniform(0,2*np.pi)
    P4=P3+L2*np.array([np.cos(a2),np.sin(a2)])
    D=np.linalg.norm(P4-P2); ex=(P4-P2)/D; ey=np.array([-ex[1],ex[0]]); rel=AX0-P2; ax_loc=[rel@ex,rel@ey]
    F=np.array([rng.uniform(0.05,0.18),rng.uniform(0.24,0.34)])
    ang=rng.uniform(0,2*np.pi); S=F+E2E*np.array([np.cos(ang),np.sin(ang)])
    if np.linalg.norm(S-P1)>0.13: return None
    lx=(P2-P1)/L1; ly=np.array([-lx[1],lx[0]]); rs=S-P1; S_loc=[rs@lx,rs@ly]
    # branch flag so that the initial P4 is reproduced
    v=P3-P2; d=np.linalg.norm(v); a=(D**2-L2**2+d**2)/(2*d); h=np.sqrt(max(0,D**2-a**2)); m=P2+a*v/d; perp=np.array([-v[1],v[0]])/d
    br=1 if np.linalg.norm(m+h*perp-P4)<np.linalg.norm(m-h*perp-P4) else -1
    return [*P1,L1,*P3,L2,D,*ax_loc,*S_loc,*F,th0,1,br]
rng=np.random.default_rng(7); cands=[]
for k in range(200000):
    p=build(rng)
    if p is None: continue
    for sgn in (1,-1):
        p[14]=sgn; c=cost(p)
        if c<1e3: cands.append((c,list(p)))
cands.sort(key=lambda t:t[0]); print('feasible',len(cands),'best raw costs',[round(c,3) for c,_ in cands[:5]])
best=None
for c,p in cands[:24]:
    fixed=(p[14],p[15]); x0=np.array(p[:14])
    f=lambda x: cost(list(x)+[fixed[0],fixed[1]])
    r=minimize(f,x0,method='Nelder-Mead',options=dict(maxiter=6000,xatol=1e-7,fatol=1e-10))
    if best is None or r.fun<best[0]: best=(r.fun,list(r.x)+[fixed[0],fixed[1]])
c,p=best; m=metrics(p)
print('cost %.4f travel %.1f mm LR0 %.3f LR65 %.3f e2e %.1f axle0 %s prog %.1f%% xshift %.1f mm' % (c,m['travel']*1000,m['lr0'],m['lr65'],m['e2e']*1000,np.round(m['axle0'],4),(m['lr0']-m['lr65'])/m['lr0']*100,m['xshift']*1000))
names=['P1x','P1y','L1','P3x','P3y','L2','D','AXx','AXy','Sx','Sy','Fx','Fy','th0','sgn','br']
print('JS: {'+', '.join(f'{n}:{v:.5f}' for n,v in zip(names,p))+'}')
r=m['raw']
for lab,row in (('start',r[0]),('end',r[-1])): print(lab,'P2',np.round(row[3],4),'P4',np.round(row[4],4),'S',np.round(row[5],4),'axle',np.round(row[1],4),'th %.3f'%row[0])
print('LR', np.round(m['lr'][::10],3))
print('stroke->travel', [(round(s*1000),round(t*1000)) for s,t in zip(m['stroke'][::12],m['trav'][::12])])
