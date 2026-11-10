/** Runs before the page paints (inlined by the root layout), so a saved theme never flashes the wrong one. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("kb-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
