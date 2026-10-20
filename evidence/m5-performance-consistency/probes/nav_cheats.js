// Navigate via header nav link (native anchor click)
(() => {
  const a = document.querySelector('a[href="/cheats"]');
  if (a) { a.click(); return {clicked:true}; }
  return {clicked:false};
})();
