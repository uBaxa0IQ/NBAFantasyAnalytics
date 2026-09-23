const TOOL_ROUTES = new Set(['mock', 'constructor']);

const pathName = () => (window.location.pathname || '/').replace(/\/$/, '') || '/';

export const isAppRoute = name => (
    window.location.hash === `#/${name}` || pathName() === `/${name}`
);

export const currentToolRoute = () => {
    const hash = (window.location.hash || '').replace(/^#\/?/, '');
    if (TOOL_ROUTES.has(hash)) return hash;
    const path = pathName().slice(1);
    if (TOOL_ROUTES.has(path)) return path;
    return null;
};

export const normalizeToolHash = () => {
    const path = pathName().slice(1);
    if (!TOOL_ROUTES.has(path) || window.location.hash === `#/${path}`) return;
    window.history.replaceState({}, '', `/#/${path}`);
};

export const openAppRoute = name => {
    if (!name) {
        window.history.replaceState({}, '', '/');
        window.location.hash = '';
        window.dispatchEvent(new PopStateEvent('popstate'));
        return;
    }
    if (pathName() !== '/') window.history.replaceState({}, '', '/');
    window.location.hash = `#/${name}`;
};

export const openConstructor = (innerTab = 'constructor') => {
    try { sessionStorage.setItem('constructor-inner-tab', innerTab === 'players' ? 'players' : 'constructor'); } catch { /* ignore */ }
    openAppRoute('constructor');
};
