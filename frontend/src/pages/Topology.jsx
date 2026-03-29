import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

// ── Layout helpers ───────────────────────────────────────────

function layoutNodes(nodes, edges) {
  // Determine tiers: firewalls → routers → switches, positioned top to bottom
  const tiers = { firewall: 0, router: 1, switch: 2, unknown: 2 };
  const grouped = {};
  nodes.forEach((n) => {
    const tier = tiers[n.device_type] ?? 2;
    (grouped[tier] = grouped[tier] || []).push(n);
  });

  // Sort within each tier by hostname for stable ordering
  Object.values(grouped).forEach((g) => g.sort((a, b) => a.hostname.localeCompare(b.hostname)));

  const positions = {};
  const tierKeys = Object.keys(grouped).sort((a, b) => a - b);
  const TIER_Y_GAP = 200;
  const NODE_X_GAP = 160;
  const PADDING_X = 80;
  const START_Y = 60;

  // Find widest tier to center others
  const maxWidth = Math.max(...tierKeys.map((t) => (grouped[t].length - 1) * NODE_X_GAP));

  tierKeys.forEach((tier, tierIdx) => {
    const group = grouped[tier];
    const tierWidth = (group.length - 1) * NODE_X_GAP;
    const offsetX = PADDING_X + (maxWidth - tierWidth) / 2;
    const y = START_Y + tierIdx * TIER_Y_GAP;
    group.forEach((node, i) => {
      positions[node.id] = { x: offsetX + i * NODE_X_GAP, y };
    });
  });

  return positions;
}

// ── Colors / icons ───────────────────────────────────────────

const DEVICE_ICONS = {
  router: 'router',
  switch: 'lan',
  firewall: 'shield',
  unknown: 'device_unknown',
};

const EDGE_COLORS = {
  optimal: { stroke: '#006c4f', label: 'Optimal' },
  congested: { stroke: '#e88a0c', label: 'Congested' },
  critical: { stroke: '#ba1a1a', label: 'Critical' },
};

const ZONE_COLORS = [
  { fill: 'rgba(0, 99, 235, 0.06)', stroke: 'rgba(0, 99, 235, 0.25)', text: '#0063eb' },
  { fill: 'rgba(0, 108, 79, 0.06)', stroke: 'rgba(0, 108, 79, 0.25)', text: '#006c4f' },
  { fill: 'rgba(232, 138, 12, 0.06)', stroke: 'rgba(232, 138, 12, 0.25)', text: '#b86e00' },
  { fill: 'rgba(156, 39, 176, 0.06)', stroke: 'rgba(156, 39, 176, 0.25)', text: '#7b1fa2' },
  { fill: 'rgba(0, 150, 136, 0.06)', stroke: 'rgba(0, 150, 136, 0.25)', text: '#00796b' },
  { fill: 'rgba(186, 26, 26, 0.06)', stroke: 'rgba(186, 26, 26, 0.25)', text: '#ba1a1a' },
];

const EDGE_TYPE_STYLE = {
  bgp: { dash: undefined, width: 2.5 },
  subnet: { dash: '6 3', width: 1.5 },
};

// ── Components ───────────────────────────────────────────────

function ToolbarButton({ icon, onClick, label, active }) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
        active ? 'bg-primary/10 text-primary' : 'hover:bg-outline-variant/30 text-on-surface-variant'
      }`}
    >
      <Icon name={icon} className="text-[20px]" />
    </button>
  );
}

function DeviceNode({ node, pos, selected, onClick, edgeCount, onDragStart }) {
  const isFirewall = node.device_type === 'firewall';
  const hasSnap = node.has_snapshot;
  const icon = DEVICE_ICONS[node.device_type] || DEVICE_ICONS.unknown;

  let ringCls, bgCls, iconCls;
  if (selected) {
    ringCls = 'ring-4 ring-primary/30';
    bgCls = 'bg-primary';
    iconCls = 'text-on-primary';
  } else if (!hasSnap) {
    ringCls = 'ring-1 ring-outline-variant/50';
    bgCls = 'bg-surface-container-high';
    iconCls = 'text-on-surface-variant';
  } else if (isFirewall) {
    ringCls = 'ring-2 ring-amber-400/40';
    bgCls = 'bg-amber-400/10';
    iconCls = 'text-amber-500';
  } else {
    ringCls = 'ring-1 ring-outline-variant';
    bgCls = 'bg-surface-container-lowest';
    iconCls = 'text-on-surface-variant';
  }

  return (
    <g
      transform={`translate(${pos.x}, ${pos.y})`}
      onClick={(e) => onClick(node, e)}
      onMouseDown={(e) => onDragStart(e, node.id)}
      className="cursor-grab active:cursor-grabbing"
    >
      {/* Background circle */}
      <circle cx={0} cy={0} r={28} className={`fill-current ${selected ? 'text-primary/5' : 'text-transparent'}`} />

      {/* Node body — use foreignObject for Tailwind styling */}
      <foreignObject x={-24} y={-24} width={48} height={48}>
        <div
          className={`w-12 h-12 rounded-xl ${bgCls} ${ringCls} flex items-center justify-center shadow-sm transition-all hover:scale-110 hover:shadow-md`}
        >
          <Icon name={icon} className={`text-[22px] ${iconCls}`} />
        </div>
      </foreignObject>

      {/* Label */}
      <text
        y={40}
        textAnchor="middle"
        className="text-[11px] font-bold fill-current text-on-surface-variant select-none"
      >
        {node.hostname}
      </text>

      {/* No snapshot indicator */}
      {!hasSnap && (
        <foreignObject x={14} y={-30} width={18} height={18}>
          <div className="w-4 h-4 rounded-full bg-outline-variant/40 flex items-center justify-center">
            <Icon name="cloud_off" className="text-[10px] text-on-surface-variant" />
          </div>
        </foreignObject>
      )}
    </g>
  );
}

function EdgeLine({ edge, fromPos, toPos, showLabels }) {
  const style = EDGE_TYPE_STYLE[edge.type] || EDGE_TYPE_STYLE.subnet;
  const color = EDGE_COLORS[edge.health]?.stroke || EDGE_COLORS.optimal.stroke;

  const mx = (fromPos.x + toPos.x) / 2;
  const my = (fromPos.y + toPos.y) / 2;

  return (
    <g>
      <line
        x1={fromPos.x}
        y1={fromPos.y}
        x2={toPos.x}
        y2={toPos.y}
        stroke={color}
        strokeWidth={style.width}
        strokeOpacity={0.5}
        strokeDasharray={style.dash}
      />
      {showLabels && edge.label && (
        <>
          <rect
            x={mx - 40}
            y={my - 8}
            width={80}
            height={16}
            rx={4}
            fill="white"
            fillOpacity={0.9}
            stroke={color}
            strokeWidth={0.5}
          />
          <text
            x={mx}
            y={my + 3.5}
            textAnchor="middle"
            className="text-[9px] font-bold select-none"
            fill={color}
          >
            {edge.label}
          </text>
        </>
      )}
    </g>
  );
}

function DetailPanel({ node, edges, allNodes, onClose }) {
  const nodeEdges = edges.filter((e) => e.from === node.id || e.to === node.id);
  const nodeMap = {};
  allNodes.forEach((n) => { nodeMap[n.id] = n; });

  return (
    <div className="w-[380px] shrink-0 bg-surface-container-low border-l border-outline-variant/40 flex flex-col overflow-y-auto">
      {/* Header */}
      <div className="p-6 pb-4 border-b border-outline-variant/30">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {node.device_type}
          </span>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container-high transition-colors">
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold text-on-surface">{node.hostname}</h2>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-on-surface-variant font-mono">{node.management_ip}</span>
          <span className="text-xs text-outline-variant">|</span>
          <span className="text-xs text-on-surface-variant">{node.platform}</span>
          {node.tags?.site && (
            <>
              <span className="text-xs text-outline-variant">|</span>
              <span className="text-xs text-on-surface-variant">{node.tags.site}</span>
            </>
          )}
        </div>
      </div>

      {/* Interfaces summary */}
      <div className="p-6 pb-2">
        <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-3">Interfaces</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-surface-container-lowest rounded-xl p-4">
            <p className="text-[11px] text-on-surface-variant mb-1">Up</p>
            <p className="text-2xl font-extrabold text-secondary">{node.interfaces_up}</p>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-4">
            <p className="text-[11px] text-on-surface-variant mb-1">Total</p>
            <p className="text-2xl font-extrabold text-on-surface">{node.interfaces_total}</p>
          </div>
        </div>
      </div>

      {/* Neighbors */}
      <div className="px-6 py-4 flex-1">
        <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-3">
          Connections ({nodeEdges.length})
        </p>
        <div className="space-y-2">
          {nodeEdges.map((edge, i) => {
            const peerId = edge.from === node.id ? edge.to : edge.from;
            const peer = nodeMap[peerId];
            const healthColor = EDGE_COLORS[edge.health];
            return (
              <div key={i} className="flex items-center gap-3 bg-surface-container-lowest rounded-lg px-4 py-3">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Icon
                    name={DEVICE_ICONS[peer?.device_type] || 'device_unknown'}
                    className="text-base text-primary"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold text-on-surface truncate">
                    {peer?.hostname || peerId.slice(0, 8)}
                  </div>
                  <div className="text-[10px] text-on-surface-variant">{edge.label}</div>
                </div>
                <div className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: healthColor?.stroke || '#006c4f' }}
                  />
                  <span className="text-[10px] font-bold text-on-surface-variant capitalize">
                    {edge.type}
                  </span>
                </div>
              </div>
            );
          })}
          {nodeEdges.length === 0 && (
            <div className="flex flex-col items-center py-6 text-on-surface-variant">
              <Icon name="link_off" className="text-2xl mb-2 opacity-40" />
              <p className="text-xs font-semibold">No connections detected</p>
              <p className="text-[10px] mt-1 opacity-60">Take a snapshot to discover neighbors</p>
            </div>
          )}
        </div>
      </div>

      {/* Snapshot status */}
      <div className="px-6 py-4 border-t border-outline-variant/30">
        <div className="flex items-center gap-2">
          <Icon
            name={node.has_snapshot ? 'check_circle' : 'cloud_off'}
            className={`text-base ${node.has_snapshot ? 'text-secondary' : 'text-on-surface-variant'}`}
          />
          <span className="text-xs text-on-surface-variant">
            {node.has_snapshot ? 'Snapshot data available' : 'No snapshot — take one to see full topology'}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

export default function Topology() {
  const { data: topologyData, loading, refetch } = useApi(api.topology);
  const [selectedNode, setSelectedNode] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [showLabels, setShowLabels] = useState(false);
  const [filterType, setFilterType] = useState('bgp');
  const [mode, setMode] = useState('pointer'); // 'pointer' | 'select'
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const isPanning = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  const nodes = topologyData?.nodes || [];
  const edges = topologyData?.edges || [];

  // Filter edges by type
  const filteredEdges = filterType === 'all'
    ? edges
    : edges.filter((e) => e.type === filterType);

  // Layout — initialize from auto-layout, then allow dragging
  // Layout is always computed from ALL edges — changing the filter should not reposition nodes
  const initialPositions = useMemo(() => layoutNodes(nodes, edges), [nodes, edges]);
  const [positions, setPositions] = useState({});
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selRect, setSelRect] = useState(null); // { x1,y1,x2,y2 } in SVG coords
  const [zones, setZones] = useState([]); // [{ id, x, y, w, h, label, color }]
  const [editingZone, setEditingZone] = useState(null); // zone id being label-edited
  const dragging = useRef(null); // { id, startX, startY, origins: {id: {x,y}} }
  const selecting = useRef(null); // { startClientX, startClientY }
  const drawingZone = useRef(null); // { x1, y1 } in SVG coords
  const serverLayout = useRef(null); // loaded layout from API
  const layoutReady = useRef(false); // prevents saving before initial load completes
  const userModified = useRef(false); // true once user drags a node or edits zones

  // Load saved layout from server on mount
  useEffect(() => {
    api.topologyLayout().then((data) => {
      serverLayout.current = data;
      if (data.zones?.length) setZones(data.zones);
      layoutReady.current = true;
    }).catch(() => { layoutReady.current = true; });
  }, []);

  // Sync positions when topology data changes, restoring saved positions
  useEffect(() => {
    const saved = serverLayout.current?.positions || {};
    setPositions(() => {
      const next = { ...initialPositions };
      for (const id in saved) {
        if (next[id]) {
          next[id] = { ...saved[id], _dragged: true };
        }
      }
      return next;
    });
  }, [initialPositions]);

  // Debounced save to server when positions or zones change (only after user interaction)
  const saveTimer = useRef(null);
  useEffect(() => {
    if (!layoutReady.current || !userModified.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const dragged = {};
      for (const id in positions) {
        if (positions[id]._dragged) {
          dragged[id] = { x: positions[id].x, y: positions[id].y };
        }
      }
      api.saveTopologyLayout({ positions: dragged, zones }).catch(() => {});
    }, 1000);
    return () => clearTimeout(saveTimer.current);
  }, [positions, zones]);

  // Calculate SVG viewBox from positions
  const viewBox = useMemo(() => {
    const xs = Object.values(positions).map((p) => p.x);
    const ys = Object.values(positions).map((p) => p.y);
    if (!xs.length) return { x: 0, y: 0, w: 1200, h: 700 };
    const pad = 100;
    const minX = Math.min(...xs) - pad;
    const minY = Math.min(...ys) - pad;
    const maxX = Math.max(...xs) + pad;
    const maxY = Math.max(...ys) + pad + 50;
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }, [positions]);

  // Zoom-to-fit on initial load
  const hasFitted = useRef(false);
  useEffect(() => {
    if (hasFitted.current) return;
    const container = containerRef.current;
    if (!container || Object.keys(positions).length === 0) return;
    hasFitted.current = true;
    requestAnimationFrame(() => {
      const rect = container.getBoundingClientRect();
      const cw = rect.width;
      const ch = rect.height;
      if (!cw || !ch || !viewBox.w || !viewBox.h) return;
      const scaleX = cw / viewBox.w;
      const scaleY = ch / viewBox.h;
      const fitZoom = Math.min(scaleX, scaleY, 1.5) * 0.9; // 90% to add breathing room, cap at 1.5x
      const contentCx = viewBox.x + viewBox.w / 2;
      const contentCy = viewBox.y + viewBox.h / 2;
      const fitPanX = cw / 2 - contentCx * fitZoom;
      const fitPanY = ch / 2 - contentCy * fitZoom;
      setZoom(fitZoom);
      setPan({ x: fitPanX, y: fitPanY });
    });
  }, [positions, viewBox]);

  // All interaction state is stored in refs to avoid stale closures.
  // A single forceUpdate counter triggers re-renders when needed.
  const [, forceRender] = useState(0);
  const stateRef = useRef({ pan, zoom, positions, selectedIds, mode, zones, selRect });
  stateRef.current = { pan, zoom, positions, selectedIds, mode, zones, selRect };

  // Node drag start
  const handleNodeDragStart = useCallback((e, nodeId) => {
    e.stopPropagation();
    const { positions: pos, selectedIds: sel } = stateRef.current;
    const ids = sel.has(nodeId) && sel.size > 1 ? [...sel] : [nodeId];
    const origins = {};
    ids.forEach((id) => { origins[id] = { x: pos[id]?.x ?? 0, y: pos[id]?.y ?? 0 }; });
    dragging.current = { ids, startX: e.clientX, startY: e.clientY, origins };
  }, []);

  // Single effect to manage all canvas mouse interaction via the container div
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const getSvgPt = (clientX, clientY) => {
      const rect = svgRef.current?.getBoundingClientRect() || { left: 0, top: 0 };
      const { pan: p, zoom: z } = stateRef.current;
      return { x: (clientX - rect.left - p.x) / z, y: (clientY - rect.top - p.y) / z };
    };

    const onMouseDown = (e) => {
      if (e.button !== 0 || dragging.current) return;
      // Defer so React synthetic onMouseDown on nodes can set dragging.current first
      const clientX = e.clientX, clientY = e.clientY;
      requestAnimationFrame(() => {
        if (dragging.current) return; // node drag won the race
        const { mode: m } = stateRef.current;
        if (m === 'select') {
          const pt = getSvgPt(clientX, clientY);
          selecting.current = true;
          setSelRect({ x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y });
        } else if (m === 'zone') {
          const pt = getSvgPt(clientX, clientY);
          drawingZone.current = true;
          setSelRect({ x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y });
        } else {
          isPanning.current = true;
          lastMouse.current = { x: clientX, y: clientY };
        }
      });
    };

    const onMouseMove = (e) => {
      if (dragging.current) {
        const d = dragging.current;
        const z = stateRef.current.zoom;
        const dx = (e.clientX - d.startX) / z;
        const dy = (e.clientY - d.startY) / z;
        setPositions((prev) => {
          const next = { ...prev };
          d.ids.forEach((id) => {
            const orig = d.origins[id];
            if (orig) { next[id] = { x: orig.x + dx, y: orig.y + dy, _dragged: true }; userModified.current = true; }
          });
          return next;
        });
        return;
      }
      if (selecting.current || drawingZone.current) {
        const pt = getSvgPt(e.clientX, e.clientY);
        setSelRect((prev) => prev ? { ...prev, x2: pt.x, y2: pt.y } : prev);
        return;
      }
      if (isPanning.current) {
        const dx = e.clientX - lastMouse.current.x;
        const dy = e.clientY - lastMouse.current.y;
        lastMouse.current = { x: e.clientX, y: e.clientY };
        setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
      }
    };

    const onMouseUp = (e) => {
      if (dragging.current) {
        dragging.current = null;
        return;
      }
      const sr = stateRef.current.selRect;
      if (drawingZone.current && sr) {
        const w = Math.abs(sr.x2 - sr.x1);
        const h = Math.abs(sr.y2 - sr.y1);
        if (w > 20 && h > 20) {
          const zs = stateRef.current.zones;
          const newZone = {
            id: `zone-${Date.now()}`,
            x: Math.min(sr.x1, sr.x2), y: Math.min(sr.y1, sr.y2), w, h,
            label: 'New Zone',
            color: ZONE_COLORS[zs.length % ZONE_COLORS.length],
          };
          setZones((prev) => [...prev, newZone]);
          userModified.current = true;
          setEditingZone(newZone.id);
        }
        drawingZone.current = null;
        setSelRect(null);
        return;
      }
      if (selecting.current && sr) {
        const minX = Math.min(sr.x1, sr.x2), maxX = Math.max(sr.x1, sr.x2);
        const minY = Math.min(sr.y1, sr.y2), maxY = Math.max(sr.y1, sr.y2);
        if (Math.abs(sr.x2 - sr.x1) > 2 || Math.abs(sr.y2 - sr.y1) > 2) {
          const pos = stateRef.current.positions;
          const inside = new Set();
          for (const id in pos) {
            const p = pos[id];
            if (p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY) inside.add(id);
          }
          if (e.shiftKey) {
            setSelectedIds((prev) => new Set([...prev, ...inside]));
          } else {
            setSelectedIds(inside);
          }
        }
        selecting.current = null;
        setSelRect(null);
        return;
      }
      isPanning.current = false;
    };

    const onWheel = (e) => {
      e.preventDefault();
      setZoom((z) => Math.min(2.5, Math.max(0.3, z - e.deltaY * 0.001)));
    };

    container.addEventListener('mousedown', onMouseDown);
    container.addEventListener('mousemove', onMouseMove);
    container.addEventListener('mouseup', onMouseUp);
    container.addEventListener('mouseleave', onMouseUp);
    container.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      container.removeEventListener('mousedown', onMouseDown);
      container.removeEventListener('mousemove', onMouseMove);
      container.removeEventListener('mouseup', onMouseUp);
      container.removeEventListener('mouseleave', onMouseUp);
      container.removeEventListener('wheel', onWheel);
    };
  }, []); // Empty deps — reads everything from refs

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.2, 2.5));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.2, 0.3));
  const handleReset = () => { setZoom(1); setPan({ x: 0, y: 0 }); setPositions(initialPositions); setZones([]); api.saveTopologyLayout({ positions: {}, zones: [] }).catch(() => {}); };

  // Edge counts per node
  const edgeCounts = {};
  filteredEdges.forEach((e) => {
    edgeCounts[e.from] = (edgeCounts[e.from] || 0) + 1;
    edgeCounts[e.to] = (edgeCounts[e.to] || 0) + 1;
  });

  // Stats
  const bgpCount = edges.filter((e) => e.type === 'bgp').length;
  const subnetCount = edges.filter((e) => e.type === 'subnet').length;
  const snappedCount = nodes.filter((n) => n.has_snapshot).length;

  return (
    <div className="flex h-[calc(100vh-10rem)] rounded-xl overflow-hidden border border-outline-variant/20" style={{ contain: 'strict' }}>
      {/* Canvas */}
      <div ref={containerRef} className="flex-1 relative bg-surface-container-low topology-grid overflow-hidden" style={{ isolation: 'isolate' }}>
        {/* Toolbar */}
        <div className="absolute top-4 left-4 z-20 bg-surface/95 rounded-xl shadow-lg border border-outline-variant/30 flex flex-col gap-0.5 p-1.5">
          <ToolbarButton icon="zoom_in" onClick={handleZoomIn} label="Zoom in" />
          <ToolbarButton icon="zoom_out" onClick={handleZoomOut} label="Zoom out" />
          <div className="h-px bg-outline-variant/40 mx-1.5 my-0.5" />
          <ToolbarButton icon="center_focus_strong" onClick={handleReset} label="Reset view" />
          <ToolbarButton icon="label" onClick={() => setShowLabels(!showLabels)} label="Toggle labels" active={showLabels} />
          <ToolbarButton icon="refresh" onClick={refetch} label="Refresh" />
          <div className="h-px bg-outline-variant/40 mx-1.5 my-0.5" />
          <ToolbarButton icon="arrow_selector_tool" onClick={() => setMode('pointer')} label="Pointer mode" active={mode === 'pointer'} />
          <ToolbarButton icon="select_all" onClick={() => setMode('select')} label="Window select" active={mode === 'select'} />
          <ToolbarButton icon="rectangle" onClick={() => setMode('zone')} label="Add zone" active={mode === 'zone'} />
        </div>

        {/* Stats bar */}
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-surface/95 rounded-full shadow-md border border-outline-variant/30 px-5 py-2 flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
            <span className="text-xs font-bold text-on-surface">{nodes.length} Devices</span>
          </div>
          <span className="text-outline-variant">|</span>
          <span className="text-[11px] text-on-surface-variant">{bgpCount} BGP</span>
          <span className="text-[11px] text-on-surface-variant">{subnetCount} Subnet</span>
          <span className="text-outline-variant">|</span>
          <span className="text-[11px] text-on-surface-variant">{snappedCount}/{nodes.length} Snapped</span>
          {selectedIds.size > 0 && (
            <>
              <span className="text-outline-variant">|</span>
              <span className="text-[11px] font-bold text-primary">{selectedIds.size} Selected</span>
            </>
          )}
        </div>

        {/* Filter pills */}
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 flex gap-1.5 mt-2">
          {['all', 'bgp', 'subnet'].map((t) => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              className={`px-3 py-1 rounded-full text-[11px] font-bold transition-all ${
                filterType === t
                  ? 'bg-primary text-on-primary shadow-sm'
                  : 'bg-surface/95 text-on-surface-variant hover:bg-outline-variant/20 border border-outline-variant/30'
              }`}
            >
              {t === 'all' ? 'All Links' : t === 'bgp' ? 'BGP Only' : 'Subnet Only'}
            </button>
          ))}
        </div>

        {/* Legend */}
        <div className="absolute bottom-4 left-4 z-10 bg-surface/95 rounded-xl shadow-lg border border-outline-variant/30 px-4 py-3">
          <p className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase mb-2">Legend</p>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <span className="w-5 h-0.5 rounded-full bg-secondary" />
              <span className="text-[11px] text-on-surface-variant">BGP (solid)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-5 h-0.5 rounded-full bg-secondary" style={{ borderTop: '2px dashed #006c4f' }} />
              <span className="text-[11px] text-on-surface-variant">Subnet (dashed)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-5 h-0.5 rounded-full bg-error" />
              <span className="text-[11px] text-on-surface-variant">Critical</span>
            </div>
          </div>
        </div>

        {/* Loading overlay */}
        {loading && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-surface-container-low/80">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
              <span className="text-sm font-semibold text-on-surface-variant">Building topology...</span>
            </div>
          </div>
        )}

        {/* SVG canvas */}
        <svg
          ref={svgRef}
          className={`absolute inset-0 w-full h-full ${mode === 'select' || mode === 'zone' ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
          onClick={(e) => {
            if (mode === 'pointer' && e.target === svgRef.current) {
              setSelectedIds(new Set());
              setSelectedNode(null);
            }
          }}
        >
          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Zones (behind everything) */}
            {zones.map((zone) => (
              <g key={zone.id}>
                <rect
                  x={zone.x}
                  y={zone.y}
                  width={zone.w}
                  height={zone.h}
                  fill={zone.color.fill}
                  stroke={zone.color.stroke}
                  strokeWidth={1.5}
                  rx={12}
                />
                {/* Label */}
                {editingZone === zone.id ? (
                  <foreignObject x={zone.x} y={zone.y - 2} width={zone.w} height={32}>
                    <input
                      autoFocus
                      className="w-full bg-white/90 border border-outline-variant/40 rounded-t-xl px-3 py-1 text-xs font-bold outline-none"
                      style={{ color: zone.color.text }}
                      defaultValue={zone.label}
                      onBlur={(e) => {
                        const val = e.target.value.trim();
                        setZones((prev) => prev.map((z) => z.id === zone.id ? { ...z, label: val || zone.label } : z));
                        userModified.current = true;
                        setEditingZone(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.target.blur();
                        if (e.key === 'Escape') { setEditingZone(null); }
                      }}
                      onClick={(e) => e.stopPropagation()}
                      onMouseDown={(e) => e.stopPropagation()}
                    />
                  </foreignObject>
                ) : (
                  <text
                    x={zone.x + 12}
                    y={zone.y + 18}
                    className="text-[11px] font-bold select-none cursor-pointer"
                    fill={zone.color.text}
                    onDoubleClick={(e) => { e.stopPropagation(); setEditingZone(zone.id); }}
                  >
                    {zone.label}
                  </text>
                )}
                {/* Delete button */}
                <foreignObject x={zone.x + zone.w - 24} y={zone.y + 2} width={22} height={22}>
                  <div
                    className="w-5 h-5 rounded-full bg-white/80 border border-outline-variant/40 flex items-center justify-center shadow-sm cursor-pointer hover:bg-error/10 hover:border-error/40 transition-colors"
                    onClick={(e) => { e.stopPropagation(); setZones((prev) => prev.filter((z) => z.id !== zone.id)); userModified.current = true; }}
                    onMouseDown={(e) => e.stopPropagation()}
                  >
                    <Icon name="close" className="text-[12px] text-on-surface-variant" />
                  </div>
                </foreignObject>
              </g>
            ))}

            {/* Edges */}
            {filteredEdges.map((edge, i) => {
              const fromPos = positions[edge.from];
              const toPos = positions[edge.to];
              if (!fromPos || !toPos) return null;
              return (
                <EdgeLine
                  key={i}
                  edge={edge}
                  fromPos={fromPos}
                  toPos={toPos}
                  showLabels={showLabels}
                />
              );
            })}

            {/* Selection / zone-drawing rectangle */}
            {selRect && (
              <rect
                x={Math.min(selRect.x1, selRect.x2)}
                y={Math.min(selRect.y1, selRect.y2)}
                width={Math.abs(selRect.x2 - selRect.x1)}
                height={Math.abs(selRect.y2 - selRect.y1)}
                fill={mode === 'zone'
                  ? ZONE_COLORS[zones.length % ZONE_COLORS.length].fill
                  : 'rgba(0, 99, 235, 0.08)'}
                stroke={mode === 'zone'
                  ? ZONE_COLORS[zones.length % ZONE_COLORS.length].stroke
                  : 'rgba(0, 99, 235, 0.4)'}
                strokeWidth={mode === 'zone' ? 1.5 : 1}
                strokeDasharray={mode === 'zone' ? undefined : '4 2'}
                rx={mode === 'zone' ? 12 : 4}
              />
            )}

            {/* Nodes */}
            {nodes.map((node) => {
              const pos = positions[node.id];
              if (!pos) return null;
              return (
                <DeviceNode
                  key={node.id}
                  node={node}
                  pos={pos}
                  selected={selectedNode?.id === node.id || selectedIds.has(node.id)}
                  onClick={(n, e) => {
                    if (e.ctrlKey || e.metaKey) {
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        next.has(n.id) ? next.delete(n.id) : next.add(n.id);
                        return next;
                      });
                    } else {
                      setSelectedIds(new Set());
                      setSelectedNode(n);
                    }
                  }}
                  edgeCount={edgeCounts[node.id] || 0}
                  onDragStart={handleNodeDragStart}
                />
              );
            })}
          </g>
        </svg>
      </div>

      {/* Detail panel */}
      {selectedNode && (
        <DetailPanel
          node={selectedNode}
          edges={edges}
          allNodes={nodes}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}
