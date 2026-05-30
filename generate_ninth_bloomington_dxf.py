#!/usr/bin/env python3
"""
Single-lane roundabout DXF — Ninth Line & Bloomington Road (YRR 40)
Bloomington Hamlet, Town of Whitchurch-Stouffville, York Region

Road context  : Rural Road (DGS p.55–57; Bloomington Rd cited as example p.56)
Design vehicle: WB-20 + farm equipment (rural setting)
Design speed  : 80 km/h approach; 30–40 km/h through roundabout
Pedestrian vol: Low (<20 ped/8h) → parallel-stripe crosswalk (DGS p.88)
Cycling       : Paved shoulder → sharrow ≥30m advance (Cycling Guidelines §5.8.1)

Design parameters derived from:
  York Region Road Design Guidelines (Dec 2025) §3.1–3.3
  Designing Great Streets Guidelines (DGS) p.55–57, p.88–89
  TAC Canadian Roundabout Design Guide (2017) — WB-20 ICD ≥ 46m, single lane
  York Region Pedestrian & Cycling Guidelines (2020) §5.8.1
  Access Guidelines for Regional Roads (2020) Table 7 (SSD @ 80 km/h = 140m)
"""

import math
from pathlib import Path

import ezdxf
from ezdxf import colors

# ---------------------------------------------------------------------------
# Design constants — Rural Road / Hamlet context
# ---------------------------------------------------------------------------

# Circulatory geometry
R_ICD       = 25.0   # Inscribed Circle radius (ICD = 50m)  — TAC min 46m for WB-20
R_CIRC_IN   = 19.0   # Inner edge of circulatory lane   (lane width = 6m)
R_TRUCK_IN  = 16.0   # Outer edge of raised central island (truck apron = 3m, rural)

# Approach road — 2-lane undivided rural, paved shoulder
LANE_W      = 3.7    # Travel lane width (rural standard)
SPLITTER_HW = 1.0    # Splitter island half-width (2m total)
SHOULDER_W  = 2.5    # Paved shoulder width (Rural Road, cycling)

CARRIAGE_HW = SPLITTER_HW + LANE_W          # 4.7m — carriageway half-width
ROAD_HW     = CARRIAGE_HW + SHOULDER_W      # 7.2m — total half-width inc. shoulder

# Longitudinal positions (in leg-local "y" = distance from centre)
YIELD_R          = 26.5
SPLITTER_NOSE_R  = 27.5
SPLITTER_BODY_R  = 28.5
SPLITTER_END     = 65.0
CROSSWALK_R      = 33.0   # parallel-stripe crosswalk near edge
SHARROW_R        = 58.0   # sharrow ≥30m advance of yield line

LEG_LENGTH  = 80.0   # leg shown from centre (extra length for rural context)

# Leg identity (axis_deg → road name, cardinal label)
LEG_META = {
    90.0:  ("NINTH LINE",      "NORTH"),
    270.0: ("NINTH LINE",      "SOUTH"),
    0.0:   ("BLOOMINGTON RD",  "EAST"),
    180.0: ("BLOOMINGTON RD",  "WEST"),
}

# ---------------------------------------------------------------------------
# Layer table
# ---------------------------------------------------------------------------
LAYERS = {
    "CURB":           colors.RED,
    "SHOULDER":       colors.YELLOW,
    "CENTRAL_ISLAND": 3,        # green
    "TRUCK_APRON":    colors.YELLOW,
    "MARKINGS":       colors.YELLOW,
    "SPLITTER_ISLAND":colors.CYAN,
    "HATCHING":       colors.GRAY,
    "ANNOTATION":     colors.WHITE,
    "DIMENSIONS":     6,        # magenta
}

ATTS = {n: {"layer": n} for n in LAYERS}

# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def to_world(x: float, y: float, axis_deg: float) -> tuple[float, float]:
    """Leg-local (x=across, y=along away from centre) → world."""
    rad = math.radians(axis_deg)
    ux, uy =  math.cos(rad),  math.sin(rad)   # along-leg
    vx, vy =  math.sin(rad), -math.cos(rad)   # right-of-leg
    return x * vx + y * ux, x * vy + y * uy


def arc_gap_angle() -> float:
    """Half-angle of the approach opening cut in the ICD circle."""
    return math.degrees(math.asin(ROAD_HW / R_ICD))


# ---------------------------------------------------------------------------
# Draw routines
# ---------------------------------------------------------------------------

def draw_circles(msp) -> None:
    """Circulatory inner kerb, truck apron inner, central island."""
    msp.add_circle((0, 0), R_CIRC_IN, dxfattribs=ATTS["TRUCK_APRON"])
    msp.add_circle((0, 0), R_TRUCK_IN, dxfattribs=ATTS["CENTRAL_ISLAND"])

    # Solid fill — central island
    hatch = msp.add_hatch(color=3, dxfattribs={"layer": "HATCHING"})
    hatch.paths.add_edge_path().add_arc((0, 0), R_TRUCK_IN, 0, 360)
    hatch.set_pattern_fill("SOLID")

    # Line hatch — truck apron (distinguishes from circulatory lane)
    apron = msp.add_hatch(color=colors.YELLOW, dxfattribs={"layer": "HATCHING"})
    apron.paths.add_edge_path().add_arc((0, 0), R_CIRC_IN,  0, 360)
    apron.paths.add_edge_path().add_arc((0, 0), R_TRUCK_IN, 0, 360)
    apron.set_pattern_fill("ANSI31", scale=0.5)


def draw_icd_arcs(msp, axes: list[float]) -> None:
    """ICD outer kerb as arcs between approach openings."""
    half = arc_gap_angle()
    gaps = sorted(((a - half) % 360, (a + half) % 360) for a in axes)

    for i, (_, end) in enumerate(gaps):
        nxt = gaps[(i + 1) % len(gaps)][0]
        if nxt <= end:
            nxt += 360
        msp.add_arc(
            center=(0, 0), radius=R_ICD,
            start_angle=end, end_angle=nxt,
            dxfattribs=ATTS["CURB"],
        )


def draw_leg(msp, axis_deg: float) -> None:
    """One approach leg: carriageway, shoulder, splitter island, markings."""
    road_name, cardinal = LEG_META[axis_deg]
    y0 = math.sqrt(R_ICD ** 2 - ROAD_HW ** 2)  # where shoulder edge meets ICD

    # --- Outer shoulder edge (dashed) ----------------------------------------
    for side in (+ROAD_HW, -ROAD_HW):
        s = to_world(side, y0,         axis_deg)
        e = to_world(side, LEG_LENGTH, axis_deg)
        # LTSCALE-aware dashed line via custom linetype: use DASHED linetype
        msp.add_line(s, e, dxfattribs={**ATTS["SHOULDER"],
                                        "linetype": "DASHED", "ltscale": 2.0})

    # --- Carriageway edge (solid) --------------------------------------------
    yc = math.sqrt(R_ICD ** 2 - CARRIAGE_HW ** 2)
    for side in (+CARRIAGE_HW, -CARRIAGE_HW):
        s = to_world(side, yc,         axis_deg)
        e = to_world(side, LEG_LENGTH, axis_deg)
        msp.add_line(s, e, dxfattribs=ATTS["CURB"])

    # Far-end cap (shoulder to shoulder)
    fl = to_world(-ROAD_HW, LEG_LENGTH, axis_deg)
    fr = to_world(+ROAD_HW, LEG_LENGTH, axis_deg)
    msp.add_line(fl, fr, dxfattribs=ATTS["CURB"])

    # --- Splitter island -------------------------------------------------------
    tip = to_world(0, SPLITTER_NOSE_R, axis_deg)
    l1  = to_world(-0.5, SPLITTER_NOSE_R + 0.5, axis_deg)
    r1  = to_world(+0.5, SPLITTER_NOSE_R + 0.5, axis_deg)
    lb  = to_world(-SPLITTER_HW, SPLITTER_BODY_R, axis_deg)
    rb  = to_world(+SPLITTER_HW, SPLITTER_BODY_R, axis_deg)
    le  = to_world(-SPLITTER_HW, SPLITTER_END,    axis_deg)
    re  = to_world(+SPLITTER_HW, SPLITTER_END,    axis_deg)
    spts = [tip, l1, lb, le, re, rb, r1, tip]
    msp.add_lwpolyline(
        [(*p, 0, 0, 0) for p in spts],
        dxfattribs=ATTS["SPLITTER_ISLAND"],
    )
    h = msp.add_hatch(color=colors.CYAN, dxfattribs={"layer": "HATCHING"})
    ep = h.paths.add_edge_path()
    for a, b in zip(spts[:-1], spts[1:]):
        ep.add_line(a, b)
    h.set_pattern_fill("SOLID")

    # --- Yield line (entry lane only) ----------------------------------------
    yl = to_world(+SPLITTER_HW, YIELD_R, axis_deg)
    yr = to_world(+CARRIAGE_HW, YIELD_R, axis_deg)
    msp.add_line(yl, yr, dxfattribs=ATTS["MARKINGS"])

    # --- Parallel-stripe crosswalk (low ped volume, DGS p.88) ----------------
    # 3 stripes, 0.5m wide, 0.5m gap — across carriageway each side of splitter
    stripe_gap = 0.5
    stripe_d   = 0.5
    for i in range(3):
        ys = CROSSWALK_R + i * (stripe_d + stripe_gap)
        ye = ys + stripe_d
        # Entry side (right of splitter)
        msp.add_line(
            to_world(+SPLITTER_HW, ys, axis_deg),
            to_world(+CARRIAGE_HW, ys, axis_deg),
            dxfattribs=ATTS["MARKINGS"],
        )
        msp.add_line(
            to_world(+SPLITTER_HW, ye, axis_deg),
            to_world(+CARRIAGE_HW, ye, axis_deg),
            dxfattribs=ATTS["MARKINGS"],
        )
        # Exit side (left of splitter)
        msp.add_line(
            to_world(-SPLITTER_HW, ys, axis_deg),
            to_world(-CARRIAGE_HW, ys, axis_deg),
            dxfattribs=ATTS["MARKINGS"],
        )
        msp.add_line(
            to_world(-SPLITTER_HW, ye, axis_deg),
            to_world(-CARRIAGE_HW, ye, axis_deg),
            dxfattribs=ATTS["MARKINGS"],
        )

    # Crosswalk end caps (outline box)
    cw_end = CROSSWALK_R + 3 * (stripe_d + stripe_gap)
    for side_from, side_to in [(+SPLITTER_HW, +CARRIAGE_HW), (-CARRIAGE_HW, -SPLITTER_HW)]:
        msp.add_lwpolyline(
            [(*to_world(x, y, axis_deg), 0, 0, 0)
             for x, y in [
                 (side_from, CROSSWALK_R), (side_to, CROSSWALK_R),
                 (side_to, cw_end),        (side_from, cw_end),
                 (side_from, CROSSWALK_R),
             ]],
            dxfattribs={**ATTS["MARKINGS"], "lineweight": 25},
        )

    # --- Sharrow (paved shoulder → cyclists share lane in roundabout) --------
    cx = (SPLITTER_HW + CARRIAGE_HW) / 2 + SPLITTER_HW  # entry lane centre
    # Chevron
    for sx in (-0.5, 0.5):
        msp.add_line(
            to_world(cx + sx * 0.6, SHARROW_R,        axis_deg),
            to_world(cx,            SHARROW_R + 0.9,  axis_deg),
            dxfattribs=ATTS["MARKINGS"],
        )
    # Bike symbol
    w1 = to_world(cx, SHARROW_R - 1.5, axis_deg)
    w2 = to_world(cx, SHARROW_R - 3.5, axis_deg)
    msp.add_circle(w1, 0.4, dxfattribs=ATTS["MARKINGS"])
    msp.add_circle(w2, 0.4, dxfattribs=ATTS["MARKINGS"])
    msp.add_line(w1, w2, dxfattribs=ATTS["MARKINGS"])

    # --- Yield text ----------------------------------------------------------
    yt = to_world(cx, YIELD_R + 4, axis_deg)
    msp.add_text(
        "YIELD",
        dxfattribs={
            "layer": "MARKINGS",
            "height": 0.9,
            "rotation": (axis_deg - 90) % 360,
            "insert": yt,
        },
    )

    # --- Road name label on approach leg ------------------------------------
    label_pos = to_world(0, LEG_LENGTH - 5, axis_deg)
    msp.add_text(
        f"{road_name} ({cardinal})",
        dxfattribs={
            "layer": "ANNOTATION",
            "height": 2.0,
            "rotation": (axis_deg - 90) % 360,
            "insert": label_pos,
        },
    )


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

def add_dimensions(msp, doc) -> None:
    # ICD span
    msp.add_linear_dim(
        base=(0, -42),
        p1=(-R_ICD, 0), p2=(R_ICD, 0),
        dimstyle="Standard",
        override={"dimpost": "ICD = <> m"},
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()

    # Central island span
    msp.add_linear_dim(
        base=(0, -36),
        p1=(-R_TRUCK_IN, 0), p2=(R_TRUCK_IN, 0),
        dimstyle="Standard",
        override={"dimpost": "ø <> CENTRAL ISLAND"},
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()

    # Approach carriageway width (north leg)
    msp.add_linear_dim(
        base=(0, 88),
        p1=(-CARRIAGE_HW, LEG_LENGTH - 3),
        p2=(+CARRIAGE_HW, LEG_LENGTH - 3),
        angle=0,
        dimstyle="Standard",
        override={"dimpost": "<> CARRIAGEWAY"},
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()

    # Shoulder width (north leg, right side)
    msp.add_linear_dim(
        base=(6.5, 88),
        p1=(+CARRIAGE_HW, LEG_LENGTH - 3),
        p2=(+ROAD_HW,     LEG_LENGTH - 3),
        angle=0,
        dimstyle="Standard",
        override={"dimpost": "<> SHOULDER"},
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()


# ---------------------------------------------------------------------------
# Title block / annotations
# ---------------------------------------------------------------------------

def add_annotations(msp) -> None:
    notes = [
        ("YORK REGION — SINGLE-LANE ROUNDABOUT",                      0, -56, 3.0),
        ("NINTH LINE & BLOOMINGTON ROAD (YRR 40)",                     0, -61, 2.5),
        ("Bloomington Hamlet, Town of Whitchurch-Stouffville",         0, -65, 1.8),
        ("",                                                           0, -70, 1.0),
        ("DESIGN PARAMETERS",                                          0, -71, 1.6),
        ("ICD = 50 m  |  Circulatory lane = 6 m  |  Truck apron = 3 m (farm vehicles)",
                                                                       0, -74, 1.2),
        ("Central island Ø 32 m  |  Approach carriageway 9.4 m  |  Paved shoulder 2.5 m",
                                                                       0, -77, 1.2),
        ("Design vehicle: WB-20 + farm equipment  |  Design speed: 80 km/h approach",
                                                                       0, -80, 1.2),
        ("Stopping sight distance @ 80 km/h: 140 m min (Access Guidelines Table 7)",
                                                                       0, -83, 1.2),
        ("Crosswalk: parallel stripe (low ped. vol, DGS p.88)",        0, -86, 1.2),
        ("Cycling: paved shoulder + sharrow ≥30 m advance (Cycling Guidelines §5.8.1)",
                                                                       0, -89, 1.2),
        ("",                                                           0, -93, 1.0),
        ("REFERENCES",                                                 0, -94, 1.4),
        ("York Region Road Design Guidelines (Dec 2025) §3.1–3.3",    0, -97, 1.1),
        ("Designing Great Streets Guidelines — Rural Road p.55–57, Roundabout p.88–89",
                                                                       0,-100, 1.1),
        ("York Region Pedestrian & Cycling Planning & Design Guidelines (2020) §5.8.1",
                                                                       0,-103, 1.1),
        ("TAC Canadian Roundabout Design Guide (2017)",                0,-106, 1.1),
        ("Access Guidelines for Regional Roads (2020) Tables 6–7",    0,-109, 1.1),
        ("",                                                           0,-113, 1.0),
        ("DISCLAIMER: FOR REFERENCE ONLY.",                            0,-114, 1.5),
        ("Final designs require a PEO-sealed Intersection Control Study and",
                                                                       0,-117, 1.2),
        ("full engineering review per York Region requirements.",       0,-120, 1.2),
        # Legend
        ("LEGEND",                               -60, 30, 1.8),
        ("─── RED    Kerb lines (CURB)",          -60, 27, 1.2),
        ("─── GREEN  Central island",             -60, 24, 1.2),
        ("─── YELLOW Truck apron / markings / shoulder edge",
                                                  -60, 21, 1.2),
        ("─── CYAN   Splitter island",            -60, 18, 1.2),
        ("─── MAGENTA Dimensions",                -60, 15, 1.2),
    ]
    for text, x, y, h in notes:
        if not text:
            continue
        msp.add_text(
            text,
            dxfattribs={"layer": "ANNOTATION", "height": h, "insert": (x, y)},
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build(output_path: str | Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Register linetypes
    doc.linetypes.add(
        name="DASHED",
        pattern=[0.75, 0.5, -0.25],
        description="Dashed",
    )

    # Layers
    for name, color in LAYERS.items():
        layer = doc.layers.add(name, color=color)

    leg_axes = list(LEG_META.keys())  # 0, 90, 180, 270

    draw_circles(msp)
    draw_icd_arcs(msp, leg_axes)
    for axis in leg_axes:
        draw_leg(msp, axis)

    add_dimensions(msp, doc)
    add_annotations(msp)

    doc.saveas(str(output_path))
    print(f"DXF written: {output_path}")
    _summary()


def _summary() -> None:
    print()
    print("Ninth Line & Bloomington Road — Rural Hamlet Single-Lane Roundabout")
    print("─" * 68)
    print(f"  Context           : Rural Road (DGS p.55–57), Bloomington Hamlet")
    print(f"  ICD               : {R_ICD*2:.0f} m  (TAC CRDG; ≥46m for WB-20)")
    print(f"  Circulatory lane  : {R_ICD - R_CIRC_IN:.1f} m")
    print(f"  Truck apron       : {R_CIRC_IN - R_TRUCK_IN:.0f} m  (enlarged for farm vehicles)")
    print(f"  Central island Ø  : {R_TRUCK_IN*2:.0f} m")
    print(f"  Approach carriageway: {CARRIAGE_HW*2:.1f} m  ({LANE_W}m lane + {SPLITTER_HW}m splitter + {LANE_W}m lane)")
    print(f"  Paved shoulder    : {SHOULDER_W:.1f} m each side  (Rural Road cycling)")
    print(f"  Design speed      : 80 km/h approach / 30–40 km/h through roundabout")
    print(f"  Design vehicle    : WB-20 + farm equipment")
    print(f"  Crosswalk type    : Parallel stripe  (low ped vol, DGS p.88)")
    print(f"  Sharrow advance   : {SHARROW_R - YIELD_R:.0f} m  (≥30m per Cycling Guidelines §5.8.1)")
    print(f"  Min SSD (80 km/h) : 140 m  (Access Guidelines Table 7)")
    print()
    print("  Sources:")
    print("    York Region Road Design Guidelines (Dec 2025) §3.1–3.3")
    print("    Designing Great Streets Guidelines — Rural Road p.55–57; Roundabout p.88–89")
    print("    York Region Ped & Cycling Guidelines (2020) §5.8.1")
    print("    TAC Canadian Roundabout Design Guide (2017)")
    print("    Access Guidelines for Regional Roads (2020) Tables 6–7")
    print()


if __name__ == "__main__":
    build(Path("ninth_line_bloomington_roundabout.dxf"))
