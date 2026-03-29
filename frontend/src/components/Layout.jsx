import { useEffect, useRef } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopNav from './TopNav';

export default function Layout() {
  const { pathname } = useLocation();
  const mainRef = useRef(null);

  // Force browser repaint after navigation — works around a compositor bug
  // where GPU-accelerated layers (SVG, backdrop-filter) from the previous
  // page can prevent the new content from visually appearing.
  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    // Reading offsetHeight after toggling visibility forces a synchronous reflow+repaint
    el.style.willChange = 'contents';
    void el.offsetHeight;
    requestAnimationFrame(() => {
      el.style.willChange = '';
    });
  }, [pathname]);

  return (
    <>
      <TopNav />
      <div className="flex min-h-screen">
        <Sidebar />
        <main ref={mainRef} className="flex-1 ml-64 p-8 bg-surface">
          <Outlet key={pathname} />
        </main>
      </div>
    </>
  );
}
