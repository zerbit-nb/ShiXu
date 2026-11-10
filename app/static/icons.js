/* Local SVG primitives; no remote assets or runtime dependency. */
function uiIcon(name){
 const paths={check:'<path d="m5 12 4 4L19 6"/>',calendar:'<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 3v4M16 3v4M4 10h16"/>',done:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',inbox:'<path d="M4 4h16v16H4zM4 13h5l1 3h4l1-3h5"/>',tasks:'<path d="M9 6h11M9 12h11M9 18h11M3 6l1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/>',message:'<path d="M4 4h16v13H9l-5 4V4zM8 8h8M8 12h5"/>',plus:'<path d="M12 5v14M5 12h14"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',settings:'<path d="M4 7h16M4 17h16"/><rect x="8" y="4" width="4" height="6" rx="1"/><rect x="14" y="14" width="4" height="6" rx="1"/>'};
 const connectionPaths={
  chat:'<path d="M7 5h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-5l-5 4v-4a3 3 0 0 1-3-3V8a3 3 0 0 1 3-3Z"/>',
  chats:'<path d="M15 13h2a3 3 0 0 1 3 3v2a3 3 0 0 1-3 3l-3-2h-3a3 3 0 0 1-3-3v-1M6 4h9a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3h-5l-4 3v-3a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3Z"/>',
  model:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  filter:'<path d="M4 4h16v3l-6 6v6l-4 2v-8L4 7V4Z"/>',
  bolt:'<path d="m13 2-9 12h7l-1 8 10-13h-8l1-7Z"/>',
  download:'<path d="M12 3v11m-4-4 4 4 4-4M5 7H4v13h16V7h-1M4 15h4l2 3h4l2-3h4"/>',
  bell:'<path d="M6 9a6 6 0 0 1 12 0c0 7 3 7 3 9H3c0-2 3-2 3-9m3 12h6"/>'
 };
 return '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name]||connectionPaths[name]||paths.inbox)+'</svg>';
}
