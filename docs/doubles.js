(function(){
  var DATA=null, LOG=[], BACK=null, kind="dd";
  var MIN_TYP={dd:0.10, td:0.02};
  var $=function(id){return document.getElementById(id)};
  var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};
  var pct=function(v){return v>=0.1?(v*100).toFixed(0)+"%":(v*100).toFixed(1)+"%"};
  var x=function(v){return v.toFixed(2).replace(/\.?0+$/,"")+"x"};
  var P=function(p){return kind==="dd"?p.p_dd:p.p_td};
  var T=function(p){return kind==="dd"?p.typ_dd:p.typ_td};
  var boost=function(p){return T(p)>=MIN_TYP[kind]?P(p)/T(p):null};
  var name=function(){return kind==="dd"?"double-double":"triple-double"};

  function item(p){
    var li=document.createElement("li"); li.className="play";
    var b=boost(p);
    li.innerHTML="<span class='who'>"+esc(p.name)+(p.status?" <em>"+esc(p.status)+"</em>":"")+"</span>"+
      "<span class='game'>"+p.team+" vs "+p.opp+", ~"+Math.round(p.min)+" min, projected "+Math.round(p.exp_pts)+" pts / "+Math.round(p.exp_reb)+" reb / "+Math.round(p.exp_ast)+" ast</span>"+
      "<span class='nums'>Chance <b>"+pct(P(p))+"</b>, usual "+pct(T(p))+(b?", <b>"+x(b)+"</b> a normal game":"")+"</span>"+
      "<span class='ev'><b>"+pct(P(p))+"</b><span>"+(kind==="dd"?"2x":"3x")+"</span></span>";
    return li;
  }
  function renderTonight(){
    var ps=DATA.players.filter(function(p){return P(p)>=(kind==="dd"?0.03:0.005)});
    var top=ps.slice().sort(function(a,b){return P(b)-P(a)}).slice(0,12);
    var bo=ps.filter(function(p){return boost(p)!==null}).sort(function(a,b){return boost(b)-boost(a)}).slice(0,12);
    var o1=$("top"); o1.innerHTML=""; top.forEach(function(p){o1.appendChild(item(p))});
    var o2=$("boost"); o2.innerHTML=""; bo.forEach(function(p){o2.appendChild(item(p))});
    $("topNote").textContent="The players most likely to get a "+name()+" tonight.";
    $("boostNote").textContent="Players whose chance tonight is furthest above their own usual rate (only players who usually do it at least "+Math.round(MIN_TYP[kind]*100)+"% of the time). A bump comes from more minutes, a faster game or a friendlier matchup.";
    var tb=$("all"); tb.innerHTML="";
    ps.sort(function(a,b){return P(b)-P(a)}).forEach(function(p){
      var b=boost(p), tr=document.createElement("tr");
      tr.innerHTML="<td>"+esc(p.name)+"<span class='sub'>"+p.team+" vs "+p.opp+(p.status?", "+esc(p.status):"")+"</span></td><td>"+pct(P(p))+"</td><td>"+pct(T(p))+"</td><td class='"+(b&&b>=1.25?"pos":"")+"'>"+(b?x(b):"—")+"</td><td>"+Math.round(p.exp_pts)+"/"+Math.round(p.exp_reb)+"/"+Math.round(p.exp_ast)+"</td>";
      tb.appendChild(tr);
    });
  }
  function renderRecord(){
    var done=LOG.filter(function(r){return r["hit_"+kind]===0||r["hit_"+kind]===1});
    var live=$("live"); live.innerHTML="";
    var pk=function(r){return kind==="dd"?r.p_dd:r.p_td}, ty=function(r){return kind==="dd"?r.typ_dd:r.typ_td};
    function row(label,rows){
      if(!rows.length) return;
      var tr=document.createElement("tr");
      var m=rows.reduce(function(a,r){return a+pk(r)},0)/rows.length, h=rows.reduce(function(a,r){return a+r["hit_"+kind]},0)/rows.length;
      tr.innerHTML="<td>"+label+"</td><td>"+rows.length+"</td><td>"+pct(m)+"</td><td>"+pct(h)+"</td>"; live.appendChild(tr);
    }
    row("Everyone tracked",done);
    var byDay={}; done.forEach(function(r){(byDay[r.date]=byDay[r.date]||[]).push(r)});
    var top=[]; Object.keys(byDay).forEach(function(d){top=top.concat(byDay[d].sort(function(a,b){return pk(b)-pk(a)}).slice(0,10))});
    row("Top 10 each night",top);
    var minT=MIN_TYP[kind];
    row("Bump 1.25x or more",done.filter(function(r){return ty(r)>=minT&&pk(r)/ty(r)>=1.25}));
    row("Bump under 0.8x",done.filter(function(r){return ty(r)>=minT&&pk(r)/ty(r)<0.8}));
    $("liveWrap").hidden=!live.children.length;
    $("liveNote").textContent=done.length?("Tracked since the season started: "+done.length+" graded "+name()+" chances. The bump rows show whether a boosted game really hits more often than a player's usual rate."):"Tracking started with the season. Results show here after the first games are graded.";
    var bk=$("back"); bk.innerHTML=""; var d=BACK&&BACK[kind];
    if(d&&d.boost&&d.boost.length){
      d.boost.forEach(function(r){var tr=document.createElement("tr");tr.innerHTML="<td>"+r.label+"</td><td>"+r.n.toLocaleString()+"</td><td>"+pct(r.typical)+"</td><td>"+pct(r.model)+"</td><td>"+pct(r.actual)+"</td>"; bk.appendChild(tr)});
      $("backWrap").hidden=false;
      $("backNote").textContent="Last season, by how much better than usual the model thought each game was (players who usually do it at least "+Math.round(MIN_TYP[kind]*100)+"% of the time). Model and Actual should match.";
    } else { $("backWrap").hidden=true; $("backNote").textContent=""; }
  }
  function render(){
    document.querySelectorAll("[data-kind]").forEach(function(b){b.setAttribute("aria-pressed",b.dataset.kind===kind?"true":"false")});
    $("status").textContent=DATA.players.length+" players across "+DATA.games.length+" games."+(kind==="td"?" Triple-doubles are rare, so even the top chances are long shots.":"");
    renderTonight(); renderRecord();
  }
  document.querySelectorAll("[data-kind]").forEach(function(b){b.onclick=function(){kind=b.dataset.kind; render();}});
  var get=function(u){return fetch(u,{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})};
  Promise.all([get("data/doubles.json"),get("data/doubles_log.json"),get("data/backtest.json")]).then(function(a){
    DATA=a[0]; LOG=a[1]||[]; BACK=a[2]&&a[2].doubles;
    if(!DATA||!DATA.games||!DATA.games.length){ $("emptyTitle").textContent="No games today"; $("emptyText").textContent="The next board appears on the next game day."; $("empty").hidden=false; return; }
    var day=new Date(DATA.date+"T12:00:00"); $("when").textContent=day.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});
    $("app").hidden=false; render();
  });
})();
