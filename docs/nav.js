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
  // Little scoreboard at the top of every page: how each market's nightly Best 6 has done.
  var strip=document.createElement("a"); strip.className="b6strip"; strip.href="doubles.html"; strip.hidden=true;
  strip.setAttribute("aria-label","Best 6 record by market");
  document.body.insertBefore(strip,document.body.firstChild);
  var short={dd:"2x",thr:"3PT",reb:"REB",ast:"AST"};
  fetch("data/best6_summary.json",{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).then(function(s){
    if(!s||!s.markets) return;
    var h="<span class='b6t'>Best 6 hit rate</span>";
    ["dd","thr","reb","ast"].forEach(function(k){
      var m=s.markets[k]; if(!m||!m.picks) return;
      h+="<span class='b6c'><b>"+Math.round(100*m.rate)+"%</b><i>"+short[k]+" "+m.hits+"/"+m.picks+"</i></span>";
    });
    strip.innerHTML=h; strip.hidden=false;
  }).catch(function(){});
})();
