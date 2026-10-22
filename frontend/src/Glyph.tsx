// Fixed pictogram library, one stick-figure pose per glyph key chosen by the backend (app/plan/glyph.py).
// Each pose is joint positions on a 48x48 grid: head, neck, pelvis, two arms [elbow, hand], two legs [knee, foot].
// The second limb of each pair is drawn lighter so side views read as near/far.
type P = [number, number];
type Pose = { h: P; n: P; p: P; a: [P, P][]; l: [P, P][]; floor?: boolean; extra?: JSX.Element };

const S = 2.4; // stroke width

const POSES: Record<string, Pose> = {
  stand: { h: [24, 8], n: [24, 13], p: [24, 26], a: [[[21, 19], [20, 25]], [[27, 19], [28, 25]]], l: [[[22, 35], [22, 44]], [[26, 35], [26, 44]]], floor: true },
  squat: { h: [19, 15], n: [21, 20], p: [29, 30], a: [[[16, 23], [11, 22]], [[17, 24], [12, 23]]], l: [[[19, 31], [21, 44]], [[21, 32], [24, 44]]], floor: true },
  boxsquat: {
    h: [19, 15], n: [21, 20], p: [29, 30], a: [[[17, 24], [19, 21]], [[18, 25], [20, 22]]], l: [[[19, 31], [21, 44]], [[21, 32], [24, 44]]], floor: true,
    extra: <rect x="29" y="33" width="11" height="11" rx="1" />,
  },
  lunge: { h: [25, 12], n: [25, 17], p: [25, 30], a: [[[24, 23], [24, 29]], [[26, 23], [26, 29]]], l: [[[16, 35], [16, 44]], [[29, 39], [36, 43]]], floor: true },
  stepup: {
    h: [24, 4], n: [24, 9], p: [24, 21], a: [[[20, 15], [17, 20]], [[28, 15], [30, 21]]], l: [[[17, 27], [14, 34]], [[26, 30], [28, 39]]], floor: true,
    extra: <rect x="7" y="34" width="14" height="10" rx="1" />,
  },
  hinge: { h: [11, 19], n: [15, 21], p: [27, 26], a: [[[15, 28], [16, 34]], [[16, 28], [17, 34]]], l: [[[24, 35], [24, 44]], [[26, 35], [27, 44]]], floor: true },
  bridge: { h: [7, 41], n: [12, 41], p: [23, 33], a: [[[17, 43], [22, 43]], [[16, 43], [21, 43]]], l: [[[32, 31], [34, 43]], [[33, 32], [36, 43]]], floor: true },
  calf: {
    h: [24, 6], n: [24, 11], p: [24, 24], a: [[[21, 17], [20, 23]], [[27, 17], [28, 23]]], l: [[[22, 33], [22, 42]], [[26, 33], [26, 42]]], floor: true,
    extra: <path d="M38 34 V22 M34 26 L38 21 L42 26" fill="none" />,
  },
  pushup: { h: [8, 30], n: [12, 32], p: [27, 36], a: [[[12, 38], [12, 44]], [[13, 38], [14, 44]]], l: [[[34, 39], [41, 43]], [[34, 39], [41, 43]]], floor: true },
  press: { h: [24, 10], n: [24, 15], p: [24, 28], a: [[[19, 11], [18, 4]], [[29, 11], [30, 4]]], l: [[[22, 36], [21, 44]], [[26, 36], [27, 44]]], floor: true },
  pullup: {
    h: [24, 10], n: [24, 15], p: [24, 28], a: [[[18, 10], [19, 3]], [[30, 10], [29, 3]]], l: [[[23, 36], [26, 42]], [[25, 36], [28, 42]]],
    extra: <line x1="10" y1="3" x2="38" y2="3" />,
  },
  row: { h: [11, 21], n: [15, 23], p: [28, 27], a: [[[21, 19], [18, 26]], [[15, 29], [15, 35]]], l: [[[25, 35], [25, 44]], [[27, 35], [28, 44]]], floor: true },
  fly: { h: [24, 7], n: [24, 12], p: [24, 26], a: [[[13, 12], [19, 8]], [[35, 12], [29, 8]]], l: [[[21, 35], [19, 44]], [[27, 35], [29, 44]]], floor: true },
  raise: { h: [24, 7], n: [24, 12], p: [24, 26], a: [[[17, 13], [9, 13]], [[31, 13], [39, 13]]], l: [[[22, 35], [21, 44]], [[26, 35], [27, 44]]], floor: true },
  curl: { h: [24, 7], n: [24, 12], p: [24, 26], a: [[[20, 21], [17, 14]], [[28, 21], [31, 14]]], l: [[[22, 35], [21, 44]], [[26, 35], [27, 44]]], floor: true },
  carry: {
    h: [24, 7], n: [24, 12], p: [24, 26], a: [[[20, 19], [19, 27]], [[28, 19], [29, 27]]], l: [[[21, 35], [19, 44]], [[27, 35], [29, 44]]], floor: true,
    extra: <g><rect x="16" y="27" width="6" height="4" rx="1" /><rect x="26" y="27" width="6" height="4" rx="1" /></g>,
  },
  birddog: { h: [10, 27], n: [14, 30], p: [30, 31], a: [[[14, 37], [14, 44]], [[8, 29], [3, 28]]], l: [[[30, 44], [38, 44]], [[38, 30], [45, 29]]], floor: true },
  sideplank: { h: [10, 27], n: [14, 31], p: [28, 37], a: [[[13, 43], [8, 43]], [[16, 25], [17, 18]]], l: [[[35, 40], [42, 43]], [[35, 40], [42, 43]]], floor: true },
  lateralwalk: {
    h: [24, 7], n: [24, 12], p: [24, 26], a: [[[18, 19], [21, 25]], [[30, 19], [27, 25]]], l: [[[19, 35], [15, 44]], [[29, 35], [33, 44]]], floor: true,
    extra: <line x1="20" y1="36" x2="28" y2="36" strokeDasharray="2 2" />,
  },
  twist: {
    h: [24, 7], n: [24, 12], p: [24, 26], a: [[[30, 16], [37, 12]], [[28, 17], [36, 15]]], l: [[[22, 35], [21, 44]], [[26, 35], [27, 44]]], floor: true,
    extra: <path d="M12 20 Q10 12 18 9" fill="none" />,
  },
  antirotation: {
    h: [24, 7], n: [24, 12], p: [24, 26], a: [[[18, 17], [11, 17]], [[19, 18], [12, 18]]], l: [[[22, 35], [21, 44]], [[26, 35], [27, 44]]], floor: true,
    extra: <line x1="11" y1="17.5" x2="3" y2="17.5" strokeDasharray="2 2" />,
  },
  crunch: { h: [12, 33], n: [16, 37], p: [27, 42], a: [[[21, 34], [27, 31]], [[21, 35], [26, 32]]], l: [[[33, 32], [39, 43]], [[34, 33], [40, 43]]], floor: true },
  plank: { h: [9, 31], n: [13, 34], p: [28, 36], a: [[[13, 43], [7, 43]], [[14, 43], [8, 43]]], l: [[[35, 39], [42, 43]], [[35, 39], [42, 43]]], floor: true },
  superman: { h: [8, 35], n: [12, 39], p: [27, 41], a: [[[6, 35], [2, 32]], [[7, 36], [3, 33]]], l: [[[35, 40], [43, 36]], [[35, 41], [43, 37]]], floor: true },
  run: { h: [22, 7], n: [23, 12], p: [25, 25], a: [[[18, 18], [15, 23]], [[28, 19], [31, 23]]], l: [[[18, 30], [20, 39]], [[28, 34], [34, 39]]], floor: true },
  jump: {
    h: [24, 6], n: [24, 11], p: [24, 23], a: [[[19, 7], [16, 2]], [[29, 7], [32, 2]]], l: [[[21, 31], [22, 38]], [[27, 31], [26, 38]]], floor: true,
    extra: <path d="M17 42 h4 M27 42 h4" />,
  },
  balance: { h: [24, 7], n: [24, 12], p: [24, 26], a: [[[17, 15], [10, 15]], [[31, 15], [38, 15]]], l: [[[24, 35], [24, 44]], [[17, 29], [19, 37]]], floor: true },
  circle: {
    h: [26, 7], n: [26, 12], p: [26, 26], a: [[[23, 19], [22, 25]], [[29, 19], [30, 25]]], l: [[[26, 35], [26, 44]], [[19, 29], [21, 37]]], floor: true,
    extra: <path d="M12 30 A7 7 0 1 1 18 36" fill="none" />,
  },
  reach: { h: [25, 12], n: [25, 17], p: [25, 30], a: [[[26, 10], [27, 3]], [[19, 22], [16, 29]]], l: [[[16, 35], [16, 44]], [[29, 39], [36, 43]]], floor: true },
  stretch: { h: [16, 29], n: [20, 32], p: [29, 42], a: [[[14, 37], [9, 41]], [[15, 38], [10, 42]]], l: [[[19, 42], [8, 43]], [[19, 42], [8, 43]]], floor: true },
};

export default function Glyph({ name, label, size = 44 }: { name: string; label: string; size?: number }) {
  const g = POSES[name] ?? POSES.stand;
  const limb = ([e, h]: [P, P], from: P, far: boolean) => (
    <polyline points={`${from} ${e} ${h}`} opacity={far ? 0.45 : 1} />
  );
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} role="img" aria-label={`${label} pictogram`}
      className="shrink-0 rounded-md bg-spot-soft text-spot" fill="none" stroke="currentColor" strokeWidth={S} strokeLinecap="round" strokeLinejoin="round">
      {g.floor && <line x1="2" y1="45.5" x2="46" y2="45.5" stroke="var(--color-rule)" strokeWidth={1.5} />}
      {g.extra && <g strokeWidth={1.8} opacity={0.8}>{g.extra}</g>}
      {limb(g.l[1], g.p, true)}
      {limb(g.a[1], g.n, true)}
      <line x1={g.n[0]} y1={g.n[1]} x2={g.p[0]} y2={g.p[1]} />
      {limb(g.l[0], g.p, false)}
      {limb(g.a[0], g.n, false)}
      <circle cx={g.h[0]} cy={g.h[1]} r={3.4} fill="currentColor" stroke="none" />
    </svg>
  );
}

export const GLYPH_NAMES = Object.keys(POSES);
