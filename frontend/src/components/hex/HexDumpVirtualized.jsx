// src/components/hex/HexDumpVirtualized.jsx
import React, { useEffect, useMemo, useCallback, useRef, useState, forwardRef } from 'react';
import { FixedSizeList as WindowList } from 'react-window';
import useElementSize from '../../hooks/useElementSize';
import './HexDump.css';

const EMPTY_BYTES = new Uint8Array();

const toHex = (n, pad = 2) => n.toString(16).toUpperCase().padStart(pad, '0');
const isPrint = (b) => b >= 32 && b <= 126;

/* The actual scrolling element — guarantees a thin scrollbar on the right */
const Outer = forwardRef(function Outer(props, ref) {
  // className after {...props}: react-window passes its own (empty) className,
  // which used to overwrite ours — the custom scrollbar never applied
  return <div ref={ref} {...props} className={['hx-outer', props.className].filter(Boolean).join(' ')} />;
});

const Row = React.memo(function Row({ index, style, data }) {
  const {
    buf,
    cols,
    selectedIndex,
    rangeStart,
    rangeEnd,
    setSelectedIndex,
    setRangeStart,
    setRangeEnd,
    setContextMenu,
    containerRef,
  } = data;

  const start = index * cols;
  const end = Math.min(start + cols, buf.length);

  const hexCells = [];
  const asciiCells = [];

  const onClickCell = (i, e) => {
    if (e.shiftKey && rangeStart !== null) {
      setRangeEnd(i);
      return;
    }

    setSelectedIndex(i);
    setRangeStart(i);
    setRangeEnd(null);
  };

  const onContextMenuCell = (i, e) => {
    e.preventDefault();
    // container position is computed at click time — the page may have scrolled
    const rect = containerRef.current?.getBoundingClientRect();
    const top = rect ? e.clientY - rect.top : e.clientY;
    const left = rect ? e.clientX - rect.left : e.clientX;
    setContextMenu({ x: left, y: top, index: i });
  };

  for (let i = start; i < end; i++) {
    const b = buf[i];
    const isSel = i === selectedIndex;
    const inRange =
      rangeStart !== null &&
      rangeEnd !== null &&
      i >= Math.min(rangeStart, rangeEnd) &&
      i <= Math.max(rangeStart, rangeEnd);

    const hexCls = [
      'hx-cell',
      isSel ? 'hx-sel' : '',
      inRange ? 'hx-range' : '',
      i - start === 7 ? 'hx-gap' : '',
    ]
      .filter(Boolean)
      .join(' ');

    hexCells.push(
      <span
        key={`h-${i}`}
        onClick={(e) => onClickCell(i, e)}
        onContextMenu={(e) => onContextMenuCell(i, e)}
        className={hexCls}
        title={`@${toHex(i, 6)}  hex:${toHex(b)}  dec:${b}`}
      >
        {toHex(b)}
      </span>
    );

    const printable = isPrint(b);
    const ch = printable ? String.fromCharCode(b) : '.';
    asciiCells.push(
      <span
        key={`a-${i}`}
        onClick={(e) => onClickCell(i, e)}
        onContextMenu={(e) => onContextMenuCell(i, e)}
        className={[
          'hx-asc-cell',
          printable ? 'asc-vis' : 'asc-dot',
          isSel ? 'hx-sel' : '',
          inRange ? 'hx-range' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        title={`@${toHex(i, 6)}  char:${printable ? ch : '.'}  dec:${b}`}
      >
        {ch}
      </span>
    );
  }

  for (let j = end; j < start + cols; j++) {
    hexCells.push(
      <span key={`h-${j}`} className="hx-cell hx-pad">
        {'  '}
      </span>
    );
    asciiCells.push(
      <span key={`a-${j}`} className="hx-asc-cell hx-pad">
        {' '}
      </span>
    );
  }

  return (
    <div className="hx-row" style={style}>
      <span className="hx-off">{toHex(start, 6)}:</span>
      <span className="hx-hex">{hexCells}</span>
      <span className="hx-asc">|{asciiCells}|</span>
    </div>
  );
});

export default function HexDumpVirtualized({
  bytes,
  cols = 16,
  height = 520,
  rowHeight = 22,
  asciiSize = 14,
  jumpTo = null, // { offset } — new object = new jump (the same offset works too)
}) {
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [rangeStart, setRangeStart] = useState(null);
  const [rangeEnd, setRangeEnd] = useState(null);
  const [contextMenu, setContextMenu] = useState(null);

  const buf = bytes instanceof Uint8Array ? bytes : EMPTY_BYTES;
  const rows = buf.length ? Math.ceil(buf.length / cols) : 0;

  const { ref: sizeRef, width } = useElementSize();
  const containerRef = useRef(null);
  const listRef = useRef(null);
  const listWidth = Math.max(600, width || 0);

  const setContainerNode = useCallback(
    (node) => {
      sizeRef(node);
      containerRef.current = node;
    },
    [sizeRef]
  );

  // jump to an offset (from the “File” and “Relations” tabs): the selection is set during
  // render when a new jumpTo arrives (React pattern “state that depends on a prop change”),
  // and scrolling happens as a side effect in useEffect
  const clampJump = (j) => Math.min(Math.max(0, j.offset), buf.length - 1);
  const [handledJump, setHandledJump] = useState(null);
  if (jumpTo && jumpTo !== handledJump && buf.length) {
    const i = clampJump(jumpTo);
    setHandledJump(jumpTo);
    setSelectedIndex(i);
    setRangeStart(i);
    setRangeEnd(null);
  }
  useEffect(() => {
    if (!jumpTo || !buf.length) return;
    listRef.current?.scrollToItem(
      Math.floor(Math.min(Math.max(0, jumpTo.offset), buf.length - 1) / cols),
      'center'
    );
  }, [jumpTo, buf, cols]);

  const itemData = useMemo(
    () => ({
      buf,
      cols,
      selectedIndex,
      rangeStart,
      rangeEnd,
      setSelectedIndex,
      setRangeStart,
      setRangeEnd,
      setContextMenu,
      containerRef,
    }),
    [buf, cols, selectedIndex, rangeStart, rangeEnd]
  );

  const statusText = useMemo(() => {
    if (selectedIndex === null) {
      return 'Click a byte (Shift+click = range)';
    }

    if (rangeStart === null || rangeEnd === null) {
      return `Selected: ${toHex(selectedIndex, 6)} (${buf[selectedIndex]} dec)`;
    }

    const start = Math.min(rangeStart, rangeEnd);
    const end = Math.max(rangeStart, rangeEnd);
    return `Selected: ${toHex(selectedIndex, 6)} (${buf[selectedIndex]} dec) | Range: ${toHex(start, 6)}–${toHex(end, 6)} (${end - start + 1} B)`;
  }, [buf, selectedIndex, rangeStart, rangeEnd]);

  const handleBackgroundClick = useCallback(() => {
    setContextMenu((prev) => (prev ? null : prev));
  }, []);

  return (
    <div
      ref={setContainerNode}
      className="hx-wrap"
      style={{ '--cols': cols, '--ascSize': `${asciiSize}px` }}
      onClick={handleBackgroundClick}
    >
      <WindowList
        ref={listRef}
        height={height}
        itemCount={rows}
        itemSize={rowHeight}
        width={listWidth}
        itemData={itemData}
        overscanCount={20}
        outerElementType={Outer}
      >
        {Row}
      </WindowList>

      <div className="hx-status">{statusText}</div>

      {contextMenu && (
        <div
          className="hx-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onMouseLeave={() => setContextMenu(null)}
        >
          <div className="hx-menu-head">
            @{toHex(contextMenu.index, 6)} (dec {buf[contextMenu.index]})
          </div>
          <hr />
          <button
            onClick={() => {
              navigator.clipboard?.writeText(toHex(buf[contextMenu.index]));
              setContextMenu(null);
            }}
          >
            Copy byte (HEX)
          </button>
          <button
            onClick={() => {
              navigator.clipboard?.writeText(`0x${toHex(contextMenu.index, 6)}`);
              setContextMenu(null);
            }}
          >
            Copy offset
          </button>
          <button
            onClick={() => {
              const a = rangeStart ?? contextMenu.index;
              const b = rangeEnd ?? contextMenu.index;
              const lo = Math.min(a, b);
              const hi = Math.max(a, b);
              let out = '';
              for (let i = lo; i <= hi; i += 1) {
                out += (i === lo ? '' : ' ') + toHex(buf[i]);
              }
              navigator.clipboard?.writeText(out);
              setContextMenu(null);
            }}
          >
            Copy range (HEX)
          </button>
        </div>
      )}
    </div>
  );
}
