(function(){
  var tabs=[["board.html","Tonight"],["doubles.html","Doubles"],["sim.html","Sim"],["app.html","Backtest"]];
  var here=location.pathname.split("/").pop()||"board.html";
  var nav=document.createElement("nav"); nav.className="tabbar"; nav.setAttribute("aria-label","Buckets");
  tabs.forEach(function(t){
    var a=document.createElement("a"); a.href=t[0]; a.textContent=t[1];
    if(here===t[0]) a.setAttribute("aria-current","page");
    nav.appendChild(a);
  });
  document.body.appendChild(nav);
  // Strip at the top of every page: tonight's betting-night grade (1-10, the round-robin scale from parlay.py) for each market,
  // with how that market's nightly Best 6 has hit so far underneath.
  var strip=document.createElement("a"); strip.className="b6strip"; strip.href="doubles.html"; strip.hidden=true;
  strip.setAttribute("aria-label","Betting night grades and Best 6 record");
  document.body.insertBefore(strip,document.body.firstChild);
  var tier=function(r){return r>=7?"good":r>=4?"mid":"bad"};
  var get=function(u){return fetch(u,{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})};
  Promise.all([get("data/best6_summary.json"),get("data/doubles.json"),get("data/best6.json")]).then(function(a){
    var s=a[0]&&a[0].markets||{}, d=a[1], t=a[2]&&a[2].ratings||{}, h="";
    var cell=function(label,rating,sub,tip){
      if(typeof rating!=="number") return "";
      return "<div class='b6c "+tier(rating)+"' title='"+tip+"'><span class='b6l'>"+label+"</span><b>"+rating+"<small>/10</small></b><i>"+sub+"</i></div>";
    };
    var hit=function(k){var m=s[k]; return m&&m.picks?Math.round(100*m.rate)+"% hit":"";};
    var rr=d&&d.parlay&&d.parlay.formats;
    if(rr){
      ["2","3"].forEach(function(k){
        var f=rr[k]; if(f) h+=cell("2x · "+k+"-pick",f.rating,hit("dd"),"Double-doubles, "+f.name+" round robin"+(d.parlay.better===k?" (the better format tonight)":""));
      });
    }
    [["thr","3PT"],["reb","REB"],["ast","AST"]].forEach(function(p){
      var r=t[p[0]]; if(r) h+=cell(p[1],r.rating,hit(p[0]),(s[p[0]]?s[p[0]].label:p[1])+", best format tonight: "+r.formats[r.better].name+(r.priced_legs<6?" (estimated prices)":""));
    });
    if(!h) return;
    strip.innerHTML="<div class='b6row'>"+h+"</div><div class='b6cap'>Tonight's betting grade, out of 10. Small print is the Best 6 hit rate so far.</div>";
    strip.hidden=false;
  });
})();
