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
  // Scoreboard at the top of every page: tonight's round-robin ratings (out of 10) and how each market's nightly Best 6 has done.
  var strip=document.createElement("a"); strip.className="b6strip"; strip.href="doubles.html"; strip.hidden=true;
  strip.setAttribute("aria-label","Ratings and Best 6 record");
  document.body.insertBefore(strip,document.body.firstChild);
  var short={dd:"Double-doubles",thr:"3-pointers",reb:"Rebounds",ast:"Assists"};
  var tierR=function(r){return r>=7?"good":r>=4?"mid":"bad"};          // rating out of 10
  var tierH=function(p){return p>=0.65?"good":p>=0.5?"mid":"bad"};     // Best 6 hit rate
  var get=function(u){return fetch(u,{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})};
  Promise.all([get("data/best6_summary.json"),get("data/doubles.json")]).then(function(a){
    var s=a[0], d=a[1], h="";
    var rr=d&&d.parlay&&d.parlay.formats;
    if(rr){
      h+="<div class='b6row'>";
      ["2","3"].forEach(function(k){
        var f=rr[k]; if(!f||typeof f.rating!=="number") return;
        h+="<div class='b6c big "+tierR(f.rating)+"'><span class='b6l'>"+f.name+" parlays"+(d.parlay.better===k?" · best tonight":"")+"</span>"+
           "<b>"+f.rating+"<small>/10</small></b><i>"+f.bets+" bets × $"+f.stake_each+"</i></div>";
      });
      h+="</div>";
    }
    if(s&&s.markets){
      h+="<div class='b6row four'><span class='b6t'>Best 6 hit rate, each night</span>";
      ["dd","thr","reb","ast"].forEach(function(k){
        var m=s.markets[k]; if(!m||!m.picks) return;
        h+="<div class='b6c "+tierH(m.rate)+"'><span class='b6l'>"+short[k]+"</span><b>"+Math.round(100*m.rate)+"%</b><i>"+m.hits+" of "+m.picks+"</i></div>";
      });
      h+="</div>";
    }
    if(!h) return;
    strip.innerHTML=h; strip.hidden=false;
  });
})();
