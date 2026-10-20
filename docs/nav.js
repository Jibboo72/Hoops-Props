(function(){
  var tabs=[["board.html","Tonight"],["sim.html","Sim"],["app.html","Backtest"]];
  var here=location.pathname.split("/").pop()||"board.html";
  var nav=document.createElement("nav"); nav.className="tabbar"; nav.setAttribute("aria-label","Buckets");
  tabs.forEach(function(t){
    var a=document.createElement("a"); a.href=t[0]; a.textContent=t[1];
    if(here===t[0]) a.setAttribute("aria-current","page");
    nav.appendChild(a);
  });
  document.body.appendChild(nav);
})();
