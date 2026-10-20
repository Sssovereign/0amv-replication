#!/usr/bin/env python3
"""v3 拟合 vs 官方 0AMV 对比可视化（独立离线 HTML，深色看板风格）。

用法: PYTHONUTF8=1 python scripts/viz_v3.py [--pred work/combo_v3_pred.csv]
产物: work/v3_fit_vs_official.html（双击即开）
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv import config


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pred', default=str(Path(config.WORK) / 'combo_v3_pred.csv'))
    ap.add_argument('--out', default=str(Path(config.WORK) / 'v3_fit_vs_official.html'))
    args = ap.parse_args()

    rows = []
    with open(args.pred, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append((int(r['date']), float(r['official']), float(r['fitted']),
                         float(r['dod_official']), float(r['dod_fitted'])))

    dates = [r[0] for r in rows]
    o = [r[1] for r in rows]
    f3 = [r[2] for r in rows]
    do = [r[3] for r in rows]
    df = [r[4] for r in rows]
    n = len(rows)

    FIT_LO, FIT_HI, OUT_LO = 20110104, 20231231, 20240101
    ENTRY, EXIT = 4.0, -2.3


    def ma10_series(vals):
        out = [None] * len(vals)
        for i in range(9, len(vals)):
            out[i] = sum(vals[i - 9:i + 1]) / 10
        return out


    def triggers(vals, dods):
        ma10 = ma10_series(vals)
        bulls, entry = set(), set()
        i = 0
        while i < len(vals):
            t1 = dods[i] >= ENTRY
            t2 = i > 0 and dods[i] > 0 and dods[i - 1] > 0 and dods[i - 1] + dods[i] >= ENTRY
            if t1 or t2:
                entry.add(i)
                bulls.add(i)
                i += 1
                while i < len(vals):
                    if dods[i] <= EXIT:
                        break
                    if ma10[i] is not None and vals[i] <= ma10[i]:
                        break
                    bulls.add(i)
                    i += 1
            i += 1
        return bulls, entry


    bull_o, entry_o = triggers(o, do)
    bull_f, entry_f = triggers(f3, df)
    jaccard = len(bull_o & bull_f) / len(bull_o | bull_f)

    bands = []
    run = None
    for i in range(n):
        if i in bull_o:
            if run is None:
                run = [i, i]
            else:
                run[1] = i
        elif run is not None:
            bands.append(run)
            run = None
    if run is not None:
        bands.append(run)

    err = [abs(df[i] - do[i]) for i in range(1, n)]
    fit_mask = [FIT_LO <= d <= FIT_HI for d in dates]
    out_mask = [d >= OUT_LO for d in dates]
    sim_in = 100 - sum(abs(f3[i] / o[i] - 1) for i in range(n) if fit_mask[i]) / sum(fit_mask) * 100
    sim_out = 100 - sum(abs(f3[i] / o[i] - 1) for i in range(n) if out_mask[i]) / sum(out_mask) * 100
    mae = sum(err) / len(err)
    lt1 = sum(1 for e in err if e < 1) / len(err) * 100
    fit_idx = next(i for i, d in enumerate(dates) if d >= OUT_LO)


    def fmt_date(d):
        return f'{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}'


    stats = {
        'sim_in': f'{sim_in:.1f}%', 'sim_out': f'{sim_out:.1f}%',
        'mae': f'{mae:.3f}pp', 'lt1': f'{lt1:.1f}%',
        'jac': f'{jaccard:.3f}',
        'bull_o': f'{len(bull_o)}天', 'bull_f': f'{len(bull_f)}天',
        'entry_o': len(entry_o), 'entry_f': len(entry_f),
        'range': f'{fmt_date(dates[0])} → {fmt_date(dates[-1])}',
    }

    DATA_JS = ("const D={dates:%s,official:%s,fitted:%s,dodO:%s,dodF:%s,bands:%s,fitIdx:%d,stats:%s};"
               % (dates, [round(v, 2) for v in o], [round(v, 2) for v in f3],
                  [round(v, 4) for v in do], [round(v, 4) for v in df],
                  bands, fit_idx, repr(stats).replace("'", '"').replace(':', ': ').replace(',', ', ')))

    TEMPLATE = r'''<!doctype html>
    <html lang="zh-CN">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>0AMV 活跃市值：v3 拟合对比官方</title>
    <style>
      :root{color-scheme:dark}
      *{box-sizing:border-box;margin:0;padding:0}
      body{background:#101318;color:#c9d1d9;font:14px/1.5 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;padding:14px 16px 10px}
      h1{font-size:16px;font-weight:500;color:#e6edf3}
      .sub{color:#8b949e;font-size:12px;margin-top:2px}
      .stats{color:#8b949e;font-size:12px;margin-top:6px}
      .stats b{color:#c9d1d9;font-weight:500}
      .legend{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:12px;color:#8b949e;margin-top:8px}
      .sw{display:inline-block;width:18px;height:2px;vertical-align:middle;margin-right:5px;border-radius:1px}
      .sw.band{width:12px;height:10px;border-radius:2px}
      .tools{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 4px}
      .tools button{background:#1b2129;color:#c9d1d9;border:1px solid #2d333c;border-radius:4px;padding:3px 10px;font-size:12px;cursor:pointer}
      .tools button:hover{border-color:#4d9fdb;color:#e6edf3}
      .tools button.on{border-color:#4d9fdb;color:#e6edf3;background:#16222e}
      .wrap{position:relative}
      canvas{display:block;width:100%}
      .tip{position:absolute;pointer-events:none;background:#1c2128;border:1px solid #2d333c;border-radius:5px;
           padding:7px 10px;font-size:12px;color:#c9d1d9;display:none;z-index:5;box-shadow:0 3px 10px rgba(0,0,0,.4);white-space:nowrap}
      .tip .d{color:#8b949e;margin-bottom:3px}
      .tip table{border-collapse:collapse}
      .tip td{padding:0 8px 0 0}
      .up{color:#e5534b}.down{color:#3fb950}
    </style>
    </head>
    <body>
    <h1>0AMV 活跃市值：v3 拟合对比官方</h1>
    <div class="sub" id="sub"></div>
    <div class="stats" id="stats"></div>
    <div class="legend">
      <span><span class="sw" style="background:#e6edf3"></span>官方 0AMV</span>
      <span><span class="sw" style="background:#4d9fdb"></span>v3 拟合（多尺度成交记忆+市值+成交额，水平 ridge）</span>
      <span><span class="sw band" style="background:rgba(229,83,75,.16)"></span>官方多头波段（±4%/−2.3%/MA10 口径）</span>
      <span><span class="sw" style="background:#d29922;height:1px"></span>2024 起样本外</span>
    </div>
    <div class="tools" id="tools"></div>
    <div class="wrap" id="wrap">
      <canvas id="cLevel" height="360"></canvas>
      <canvas id="cDod" height="180"></canvas>
      <div class="tip" id="tip"></div>
    </div>
    <div class="sub" style="margin-top:4px">滚轮缩放 · 拖动平移 · 双击复位 · 悬停查看逐日数值</div>
    <script>
    __DATA__
    const bg='#101318',grid='#232a33',axis='#8b949e',txt='#c9d1d9';
    const cOff='#e6edf3',cFit='#4d9fdb',cBand='rgba(229,83,75,.14)',cGold='#d29922';
    const cUp='#e5534b',cDown='#3fb950';
    const N=D.dates.length;
    let view=[0,N-1];
    const wrap=document.getElementById('wrap'),tip=document.getElementById('tip');
    const cL=document.getElementById('cLevel'),cD=document.getElementById('cDod');
    const ctxL=cL.getContext('2d'),ctxD=cD.getContext('2d');

    document.getElementById('sub').textContent='v3 = Σ 成交记忆EMA(5/10/20/60/120/250, 上限流通股本)×收盘价 + 流通市值 + 当天成交额，log 线性水平 ridge（α=0.01，2011-2023 定系数）。数据 '+D.stats.range+'，官方收盘口径。';
    document.getElementById('stats').innerHTML=
     '水平相似度：拟合内 <b>'+D.stats.sim_in+'</b> · 样本外(2024+) <b>'+D.stats.sim_out+'</b>　|　'+
     '日涨幅 MAE <b>'+D.stats.mae+'</b> · &lt;1pp 占 <b>'+D.stats.lt1+'</b>　|　'+
     '波段 Jaccard <b>'+D.stats.jac+'</b>（官方多头 '+D.stats.bull_o+' / v3 多头 '+D.stats.bull_f+'，入场触发 官方 '+D.stats.entry_o+' / v3 '+D.stats.entry_f+'）';

    const ranges=[['全部',()=>[0,N-1]],['拟合窗 2011-2023',()=>[0,D.fitIdx-1]],['样本外 2024+',()=>[D.fitIdx,N-1]],
     ['近1年',()=>[N-244,N-1]],['近3月',()=>[N-61,N-1]]];
    const tools=document.getElementById('tools');
    ranges.forEach((r,ri)=>{
      const b=document.createElement('button');b.type='button';b.textContent=r[0];
      b.addEventListener('click',()=>{view=r[1]();draw();mark(ri);});
      tools.appendChild(b);r.push(b);
    });
    function mark(on){ranges.forEach((r,i)=>r[2].classList.toggle('on',i===on));}
    mark(0);

    function layout(cv,h){const w=wrap.clientWidth,dpr=window.devicePixelRatio||1;
      cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);cv.style.height=h+'px';
      const c=cv.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);return w;}
    function fmt(v){return v>=10000?(v/10000).toFixed(1)+'万':Math.round(v).toLocaleString('en-US');}
    function fmtDate(d){return d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6,8);}
    function idx2date(i){const d=D.dates[i];return fmtDate(String(d));}

    function xAt(w,i){const p=58;return p+(w-p-10)*(i-view[0])/(view[1]-view[0]);}
    function iAt(w,x){const p=58;return view[0]+(x-p)/(w-p-10)*(view[1]-view[0]);}

    function panel(cv,ctx,h,ymin,ymax,fmtY,thr){
      const w=layout(cv,h);ctx.clearRect(0,0,w,h);
      const p=58,pr=10,top=8,bh=h-top-22;
      const y=v=>top+bh*(1-(v-ymin)/(ymax-ymin));
      // 官方多头波段（宽视图下降噪）
      const span=view[1]-view[0];
      ctx.fillStyle=span>2000?'rgba(229,83,75,.05)':span>800?'rgba(229,83,75,.09)':cBand;
      D.bands.forEach(b=>{
        const a=Math.max(b[0],view[0]),b2=Math.min(b[1],view[1]);
        if(b2>=a)ctx.fillRect(xAt(w,a),top,Math.max(xAt(w,b2)-xAt(w,a),1),bh);
      });
      // 网格+Y轴
      ctx.strokeStyle=grid;ctx.fillStyle=axis;ctx.lineWidth=1;ctx.font='11px "Segoe UI",sans-serif';
      const steps=5;
      for(let s=0;s<=steps;s++){const v=ymin+(ymax-ymin)*s/steps,yy=Math.round(y(v))+.5;
        ctx.beginPath();ctx.moveTo(p,yy);ctx.lineTo(w-pr,yy);ctx.stroke();
        ctx.textAlign='right';ctx.fillText(fmtY(v),p-6,yy+4);}
      // X 轴刻度
      const tickN=span>1500?8:span>500?6:span>120?5:4;
      ctx.textAlign='center';
      for(let s=0;s<=tickN;s++){const i=Math.min(N-1,Math.max(0,Math.round(view[0]+span*s/tickN)));
        const x=Math.round(xAt(w,i))+.5;
        ctx.strokeStyle=grid;ctx.beginPath();ctx.moveTo(x,top+bh);ctx.lineTo(x,h-20);ctx.stroke();
        ctx.fillText(idx2date(i),x,h-6);}
      // 样本外分界
      if(D.fitIdx>view[0]&&D.fitIdx<view[1]){const x=Math.round(xAt(w,D.fitIdx))+.5;
        ctx.strokeStyle=cGold;ctx.setLineDash([4,4]);
        ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+bh);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle=cGold;ctx.textAlign='left';ctx.fillText('2024 样本外',x+4,top+11);}
      // 阈值线（仅 dod 板，标签靠右）
      if(thr){thr.forEach(t=>{if(t.v>=ymin&&t.v<=ymax&&t.t){const yy=Math.round(y(t.v))+.5;
        ctx.strokeStyle=t.c;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(p,yy);ctx.lineTo(w-pr,yy);ctx.stroke();
        ctx.setLineDash([]);ctx.fillStyle=t.c;ctx.textAlign='right';ctx.fillText(t.t,w-pr-2,yy-4);}});}
      return {w,p,pr,top,bh,y};
    }

    function line(ctx,g,vals,color,lw){
      ctx.strokeStyle=color;ctx.lineWidth=lw;ctx.lineJoin='round';ctx.beginPath();
      let started=false;
      const step=Math.max(1,Math.floor((view[1]-view[0])/2000));
      for(let i=Math.max(0,Math.floor(view[0]));i<=Math.min(N-1,Math.ceil(view[1]));i+=step){
        const x=g.xAt?g.xAt(i):xAt(g.w,i),yy=g.y(vals[i]);
        if(!started){ctx.moveTo(x,yy);started=true;}else ctx.lineTo(x,yy);}
      const li=Math.min(N-1,Math.ceil(view[1]));
      if(li>=Math.max(0,Math.floor(view[0]))){const x=xAt(g.w,li);ctx.lineTo(x,g.y(vals[li]));}
      ctx.stroke();
    }

    function draw(){
      const i0=Math.max(0,Math.floor(view[0])),i1=Math.min(N-1,Math.ceil(view[1]));
      let lo=Infinity,hi=-Infinity;
      for(let i=i0;i<=i1;i++){lo=Math.min(lo,D.official[i],D.fitted[i]);hi=Math.max(hi,D.official[i],D.fitted[i]);}
      const pad=(hi-lo)*0.07||1;
      const gL=panel(cL,ctxL,360,Math.max(0,lo-pad),hi+pad,v=>fmt(v));
      gL.xAt=i=>xAt(gL.w,i);
      line(ctxL,gL,D.official,cOff,1.4);
      line(ctxL,gL,D.fitted,cFit,1.2);
      let dlo=-3,dhi=3;
      for(let i=i0;i<=i1;i++){dlo=Math.min(dlo,D.dodO[i],D.dodF[i]);dhi=Math.max(dhi,D.dodO[i],D.dodF[i]);}
      dlo=Math.min(dlo,-2.3)-1;dhi=Math.max(dhi,4)+1;
      if(dhi-dlo>60){dlo=Math.max(dlo,-15);dhi=Math.min(dhi,15);}
      const gD=panel(cD,ctxD,180,dlo,dhi,v=>v.toFixed(1)+'%',
        [{v:4,c:cUp,t:'+4% 入场'},{v:-2.3,c:cDown,t:'−2.3% 出场'},{v:0,c:grid,t:''}]);
      gD.xAt=i=>xAt(gD.w,i);
      line(ctxD,gD,D.dodO,cOff,1.2);
      line(ctxD,gD,D.dodF,cFit,1.1);
      drawCross(gD);
    }

    let crossI=null;
    function drawCross(){
      const w=wrap.clientWidth;
      [ [cL,ctxL,360],[cD,ctxD,180] ].forEach(a=>{
        const c=a[1],h=a[2];
        if(crossI==null)return;
        const x=xAt(w,crossI);
        if(x<58||x>w-10)return;
        c.strokeStyle='#59626e';c.lineWidth=1;
        c.beginPath();c.moveTo(Math.round(x)+.5,8);c.lineTo(Math.round(x)+.5,h-22);c.stroke();
      });
    }

    wrap.addEventListener('wheel',e=>{e.preventDefault();
      const w=wrap.clientWidth,x=e.clientX-wrap.getBoundingClientRect().left;
      const anchor=iAt(w,x),f=e.deltaY>0?1.25:0.8;
      let s=(view[1]-view[0])*f;s=Math.min(Math.max(s,15),N-1);
      const t=(anchor-view[0])/(view[1]-view[0]);
      view[0]=anchor-t*s;view[1]=view[0]+s;
      if(view[0]<0){view[0]=0;view[1]=s;}
      if(view[1]>N-1){view[1]=N-1;view[0]=N-1-s;}
      draw();mark(-1);hideTip();
    },{passive:false});

    let drag=null;
    wrap.addEventListener('mousedown',e=>{drag={x:e.clientX,view:view.slice()};});
    window.addEventListener('mousemove',e=>{
      if(!drag)return;
      const w=wrap.clientWidth,dx=e.clientX-drag.x;
      const di=-dx/(w-68)*(drag.view[1]-drag.view[0]);
      let a=drag.view[0]+di,b=drag.view[1]+di;
      if(a<0){a=0;b=drag.view[1]-drag.view[0];}
      if(b>N-1){b=N-1;a=b-(drag.view[1]-drag.view[0]);}
      view=[a,b];draw();mark(-1);
    });
    window.addEventListener('mouseup',()=>{drag=null;});
    wrap.addEventListener('dblclick',()=>{view=[0,N-1];draw();mark(0);hideTip();});

    function hideTip(){tip.style.display='none';crossI=null;draw();}
    function inBand(i){return D.bands.some(b=>i>=b[0]&&i<=b[1]);}
    wrap.addEventListener('mousemove',e=>{
      if(drag)return;
      const rect=wrap.getBoundingClientRect(),w=wrap.clientWidth;
      const x=e.clientX-rect.left,y=e.clientY-rect.top;
      const i=Math.round(iAt(w,x));
      if(i<view[0]||i>view[1]||i<0||i>=N||y>360+180){hideTip();return;}
      crossI=i;draw();
      const dodO=D.dodO[i],dodF=D.dodF[i];
      tip.innerHTML='<div class="d">'+idx2date(i)+'　'+(inBand(i)?'<span class="up">官方多头波段</span>':'空仓')+
        (i>=D.fitIdx?' · <span style="color:'+cGold+'">样本外</span>':'')+'</div><table>'+
        '<tr><td>官方收盘</td><td class="tab">'+D.official[i].toLocaleString('en-US')+'</td>'+
        '<td style="color:'+cOff+'">官方dod</td><td class="'+(dodO>=0?'up':'down')+'">'+(dodO>=0?'+':'')+dodO.toFixed(2)+'%</td></tr>'+
        '<tr><td>v3 拟合</td><td class="tab">'+D.fitted[i].toLocaleString('en-US')+'</td>'+
        '<td style="color:'+cFit+'">v3 dod</td><td class="'+(dodF>=0?'up':'down')+'">'+(dodF>=0?'+':'')+dodF.toFixed(2)+'%</td></tr>'+
        '<tr><td>水平偏差</td><td colspan="3" class="'+(D.fitted[i]>=D.official[i]?'up':'down')+'">'+((D.fitted[i]/D.official[i]-1)*100).toFixed(2)+'%</td></tr></table>';
      tip.style.display='block';
      const tw=tip.offsetWidth;
      tip.style.left=Math.min(Math.max(x+14,4),w-tw-6)+'px';
      tip.style.top=(y>200?y-90:y+16)+'px';
    });
    wrap.addEventListener('mouseleave',hideTip);

    if('ResizeObserver' in window){new ResizeObserver(()=>draw()).observe(wrap);}
    draw();
    </script>
    </body>
    </html>
    '''

    out = Path(args.out)
    out.write_text(TEMPLATE.replace('__DATA__', DATA_JS), encoding='utf-8')
    print(f'{out}  {out.stat().st_size/1024:.0f} KB')
    print('stats:', stats)
    print('bands:', len(bands), 'first/last:', bands[0], bands[-1])


if __name__ == '__main__':
    main()
