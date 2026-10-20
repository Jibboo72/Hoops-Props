(function(){
  var DATA=null, market="thr", game="all";
  var BEST=0.05, FLAG=0.30;
  var $=function(id){return document.getElementById(id)};
  var pct=function(v){return (v*100).toFixed(0)+"%"};
  var am=function(p){return p==null?"—":(p>0?"+"+p:""+p)};
  var ev=function(v){return (v>0?"+":"")+(v*100).toFixed(0)+"%"};
  var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};

  // "thr_o2.5" is over 2.5 threes made; "reb_u8.5" is under 8.5 rebounds. Each tab shows every line and side of its market.
  var part=function(k){var a=k.split("_"); return {fam:a[0], side:a[1][0], pt:a[1].slice(1)}};
  var lab=function(k){var p=part(k); return (p.side==="o"?"over ":"under ")+p.pt+(p.fam==="thr"?" threes":" rebounds")};
  function keys(){
    return (DATA.markets||[]).filter(function(k){return part(k).fam===market});
  }
  function rows(){
    var out=[], ks=keys();
    DATA.players.forEach(function(p){
      if(game!=="all"&&String(p.game_id)!==game) return;
      ks.forEach(function(k){ if(p[k]) out.push({p:p, m:p[k], k:k}) });
    });
    return out;
  }
  function playItem(r){
    var li=document.createElement("li"); li.className="play";
    li.innerHTML="<span class='who'>"+esc(r.p.name)+"</span>"+
      "<span class='game'>"+r.p.team+" vs "+r.p.opp+", "+lab(r.k)+", ~"+Math.round(r.p.min)+" min</span>"+
      "<span class='nums'>Model <b>"+pct(r.m.p)+"</b>, fair "+am(r.m.fair)+", best <b>"+am(r.m.price)+"</b> "+esc(r.m.book)+"</span>"+
      "<span class='ev'><b>"+ev(r.m.ev)+"</b><span>EV</span></span>";
    return li;
  }
  function renderLikely(){
    var r=DATA.likely_rules, list=[];
    DATA.players.forEach(function(p){
      if(game!=="all"&&String(p.game_id)!==game) return;
      (DATA.markets||[]).forEach(function(k){ if(p[k]&&p[k].likely) list.push({p:p, m:p[k], k:k}) });
    });
    list.sort(function(a,b){return b.m.ev-a.m.ev});
    var ol=$("likely"); ol.innerHTML="";
    list.forEach(function(x){ol.appendChild(playItem(x))});
    $("likelyBlock").hidden=!r;
    if(r) $("likelyNote").textContent = list.length
      ? "Threes or rebounds, over or under, at "+pct(r.min.thr||0.55)+"+ to hit, priced between "+(r.min_price||-250)+" and +"+r.max_price+", never more than "+Math.round(-r.price_check*100)+"% over fair. Ranked by price edge, best first."
      : "Nothing passes the hit-chance and price checks right now.";
  }
  function render(){
    renderLikely();
    document.querySelectorAll(".switch button").forEach(function(b){
      b.setAttribute("aria-pressed", b.dataset.market===market?"true":"false");
    });
    var chips=$("games"); chips.innerHTML="";
    [{id:"all",label:"All games"}].concat(DATA.games.map(function(g){return {id:String(g.id),label:g.away+" @ "+g.home}}))
      .forEach(function(g){
        var b=document.createElement("button"); b.textContent=g.label;
        b.setAttribute("aria-pressed", g.id===game?"true":"false");
        b.onclick=function(){game=g.id; render();};
        chips.appendChild(b);
      });
    var st=DATA.odds_status, gm=DATA.games.filter(function(g){return String(g.id)===game})[0];
    if(gm&&gm.total!=null){
      var sp=gm.spread_home;
      st+=" "+gm.away+" @ "+gm.home+": total "+gm.total+(sp!=null?", "+gm.home+" "+(sp>0?"+":"")+sp:"")+".";
    }
    if(DATA.unmatched&&DATA.unmatched.length) st+=" "+DATA.unmatched.length+" priced names had no match in the model.";
    $("status").textContent=st;

    var rs=rows(), priced=rs.filter(function(r){return r.m.ev!=null});
    var max=DATA.max_price||500;
    var best=priced.filter(function(r){return r.m.ev>=BEST&&r.m.ev<FLAG&&r.m.price<=max}).sort(function(a,b){return b.m.ev-a.m.ev});
    var flags=priced.filter(function(r){return r.m.ev>=FLAG}).sort(function(a,b){return b.m.ev-a.m.ev});
    var ol=$("best"); ol.innerHTML=""; best.forEach(function(r){ol.appendChild(playItem(r))});
    $("bestNote").textContent = !priced.length
      ? "No sportsbook prices yet. Use the Fair column below and compare it to your book."
      : best.length ? "Model edge of 5% or more against the best available price, at +"+max+" or shorter. Longer shots stay in the table below."
      : "Nothing at +"+max+" or shorter clears a 5% edge right now. Passing is a fine bet.";
    var fl=$("flags"); fl.innerHTML=""; fl.className="plays flagged";
    flags.forEach(function(r){fl.appendChild(playItem(r))});
    $("flagBlock").hidden=!flags.length;

    var tb=$("all"); tb.innerHTML="";
    rs.sort(function(a,b){return b.m.p-a.m.p}).forEach(function(r){
      var tr=document.createElement("tr");
      tr.innerHTML="<td>"+esc(r.p.name)+"<span class='sub'>"+r.p.team+" vs "+r.p.opp+", "+lab(r.k)+"</span></td>"+
        "<td>"+pct(r.m.p)+"</td><td>"+am(r.m.fair)+"</td><td>"+am(r.m.price)+"</td>"+
        "<td class='"+(r.m.ev>=BEST?"pos":"")+"'>"+(r.m.ev==null?"—":ev(r.m.ev))+"</td>";
      tb.appendChild(tr);
    });
  }
  document.querySelectorAll(".switch button").forEach(function(b){
    b.onclick=function(){market=b.dataset.market; render();};
  });
  fetch("data/board.json",{cache:"no-store"})
    .then(function(r){if(!r.ok) throw 0; return r.json();})
    .then(function(d){
      DATA=d;
      var day=new Date(d.date+"T12:00:00");
      $("when").textContent=day.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});
      if(!d.games.length){
        $("emptyTitle").textContent="No games today"; $("emptyText").textContent="The next board appears on the next game day.";
        $("empty").hidden=false; return;
      }
      if(!d.players.length){
        $("emptyTitle").textContent="Board is empty"; $("emptyText").textContent=d.odds_status||"No players matched yet.";
        $("empty").hidden=false; return;
      }
      $("app").hidden=false; render();
    })
    .catch(function(){ $("empty").hidden=false; });
})();
