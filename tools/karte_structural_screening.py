"""Simple structural screening for the 106 karte (Japanese schedule) bridges.

Idealizations follow the CAD reconstruction rules in karte_cad/model.py:
- girder lines: rectangle stacks from girder_profile / box-girder cuts (envelope sections)
- slab bridges: 1 m wide strip with the same longitudinal void deduction as the CAD model
- trusses: two plane trusses per superstructure from the modeled panel geometry,
  each carrying half of the deck line load at bottom-chord panel points

Loads: deck concrete 2400 kg/m^3, asphalt 2300 kg/m^3, live load 5 kPa (simplified
walkway-level screening load, not a TL-20 design verification), steel 200 GPa / 7850 kg/m^3,
concrete 25 GPa. Continuous beams are solved with a conforming hermite beam element;
reactions, bending moments (sagging positive) and deflections were calibrated against
textbook values (simply supported and two-span uniform load). Screening indicators only.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1]
CONCRETE_RHO, STEEL_RHO, ASPHALT_RHO = 2400.0, 7850.0, 2300.0
CONCRETE_E, STEEL_E = 25e9, 200e9
LIVE_PA, G = 5000.0, 9.80665

ASSUMPTIONS = [
    "簡易スクリーニング用の指標値であり、設計照査・耐荷力検証ではない（TL-20などの設計活荷重とは別基準の簡易活荷重 5 kPa を使用）",
    "断面はCADモデルと同一の包絡断面（girder_profile・箱桁外形・中空床版の縦方向の孔）から計算。合成効果・PC鋼材緊張力・局部断面・座屈・疲労は評価しない",
    "主桁の鉛直支持・水平拘束は橋軸直角方向断面内の割付をせず、床版・舗装・活荷重を主桁本数で均等分担とする（縁石・歩道・高欄・対傾構の重量は未考慮）",
    "梁は連続梁の曲げ(EI一定)で解析し、E: 鋼200GPa、コンクリート25GPa、密度: 鋼7850・コンクリート2400・舗装2300 kg/m3 と仮定",
    "トラスはCADモデルと同じパネル割(約6m)の2面トラスを独立に扱い、各面が床版線荷重の半分を負担。節点はピン接合、横構・節点モーメントを除外",
    "斜角45度未満・縦断勾配・平面曲線の幾何効果は理想化に反映しない（CADの形状とは異なる直線断面）",
]


def beam_end_forces(L, EI, q_line):
    k = EI / L ** 3
    matrix = k * np.array([[12, 6 * L, -12, 6 * L],
                           [6 * L, 4 * L * L, -6 * L, 2 * L * L],
                           [-12, -6 * L, 12, -6 * L],
                           [6 * L, 2 * L * L, -6 * L, 4 * L * L]])
    load = np.array([-q_line * L / 2, -q_line * L * L / 12, -q_line * L / 2, q_line * L * L / 12])
    return matrix, load


def continuous_beam(spans, q_line, EI, samples=41):
    nodes = np.cumsum([0.0, *spans])
    count = len(nodes)
    total = 2 * count
    K = np.zeros((total, total))
    F = np.zeros(total)
    for index, length in enumerate(spans):
        Ke, Fe = beam_end_forces(length, EI, q_line)
        dofs = [2 * index, 2 * index + 1, 2 * index + 2, 2 * index + 3]
        K[np.ix_(dofs, dofs)] += Ke
        F[dofs] += Fe
    fixed = [2 * index for index in range(count)]
    free = [dof for dof in range(total) if dof not in fixed]
    displacement = np.zeros(total)
    displacement[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    reactions = K @ displacement - F
    sagging = hogging = 0.0
    sagging_at = hogging_at = None
    worst_deflection = worst_ratio = None
    for index, length in enumerate(spans):
        Ke, Fe = beam_end_forces(length, EI, q_line)
        element_dofs = [2 * index, 2 * index + 1, 2 * index + 2, 2 * index + 3]
        fe = Ke @ displacement[element_dofs] - Fe
        start_x = nodes[index]
        M_L, V_L = -fe[1], fe[0]
        xs = start_x + np.linspace(0.0, length, samples)
        moments = M_L + V_L * (xs - start_x) - q_line * (xs - start_x) ** 2 / 2.0
        positive = moments.max()
        negative = moments.min()
        if sagging is None or positive > sagging:
            sagging, sagging_at = positive, xs[np.argmax(moments)]
        if hogging is None or negative < hogging:
            hogging, hogging_at = negative, xs[np.argmin(moments)]
        xi = np.linspace(0, 1, samples)
        N1 = 1 - 3 * xi ** 2 + 2 * xi ** 3
        N2 = length * (xi - 2 * xi ** 2 + xi ** 3)
        N3 = 3 * xi ** 2 - 2 * xi ** 3
        N4 = length * (-xi ** 2 + xi ** 3)
        d_e = displacement[element_dofs]
        free_w = -q_line * (xi * length) ** 2 * ((1 - xi) * length) ** 2 / (24.0 * EI)
        w = N1 * d_e[0] + N2 * d_e[1] + N3 * d_e[2] + N4 * d_e[3] + free_w
        downward = -w.min()
        if downward > 1e-12:
            ratio = length / downward
            if worst_ratio is None or ratio < worst_ratio:
                worst_ratio = ratio
                worst_deflection = downward
    return {"nodes_x": nodes, "reactions_N": reactions[::2],
            "max_sagging_Nm": sagging, "max_sagging_x": sagging_at,
            "max_hogging_Nm": hogging, "max_hogging_x": hogging_at,
            "max_deflection_m": worst_deflection, "worst_deflection_ratio": worst_ratio}


def section_properties(rectangles):
    """rectangles: [(width, z0, z1)] in local girder coordinates (z up, 0 at bottom)."""
    area = 0.0
    first = 0.0
    for width, z0, z1 in rectangles:
        piece = width * (z1 - z0)
        area += piece
        first += piece * (z0 + z1) / 2.0
    zc = first / area
    inertia = 0.0
    for width, z0, z1 in rectangles:
        height = z1 - z0
        inertia += width * height ** 3 / 12.0 + width * height * ((z0 + z1) / 2.0 - zc) ** 2
    top = z1_max = max(r[2] for r in rectangles)
    bottom = min(r[1] for r in rectangles)
    return {"area_m2": area, "z_centroid_m": zc, "I_m4": inertia,
            "c_top_m": top - zc, "c_bottom_m": zc - bottom, "height_m": top - bottom}


def girder_rectangles(b, s, spacing):
    """Same section rules as karte_cad/model.py girder_profile and box-girder cuts."""
    h = s["height"]
    steel = s["material"] not in ("PC", "RC")
    if "箱桁" in s["form"]:
        n = max(1, s["girder_count"])
        bw = min(b["width"] * 0.55, max(0.7, spacing * 0.55)) if n > 1 else b["width"] * 0.55
        return steel, [(bw, 0.0, 0.025), (bw, h - 0.025, h), (0.02, 0.025, h - 0.025), (0.02, 0.025, h - 0.025)]
    if steel:
        web, tf = b["steel_web"], b["steel_flange"]
        flange = min(spacing * 0.65, max(0.28, h * 0.35))
        return True, [(flange, 0.0, tf), (web, tf, h - tf), (flange, h - tf, h)]
    web = min(0.32, spacing * 0.26)
    tf = min(0.18, h * 0.2)
    return False, [(web, 0.0, h - tf), (spacing * 0.86, h - tf, h)]


def slab_strip(b, s):
    """Per-metre-width strip properties for 床版橋 superstructures."""
    t = s["height"]
    if "中空" not in s["form"]:
        return True, t, t ** 3 / 12.0
    voids = max(1, int(b["width"] / 0.8))
    pitch = b["width"] / voids
    d = min(0.5, pitch * 0.60)
    area = t - d * 0.5 * t / pitch
    inertia = (pitch * t ** 3 - d * (0.5 * t) ** 3) / 12.0 / pitch
    return False, area, inertia


def build_pratt_plane(x_positions, z_bottom, z_top, tag, sign_index):
    """Standard Pratt: chords, end posts, interior verticals and panel diagonals
    sloping down toward midspan. Statically determinate and stable."""
    nodes, node_index = [], {}
    for x in x_positions:
        for z in (z_bottom, z_top):
            key = (round(float(x), 3), z)
            if key not in node_index:
                node_index[key] = len(nodes)
                nodes.append((float(x), z))
    def add(role, i, j, A, L):
        return {"name": f"{tag}_{role}_{len(elements):02d}_{sign_index}", "role": role, "i": i, "j": j,
                "A_m2": A, "L_m": L, "E_Pa": STEEL_E, "rho": STEEL_RHO}
    elements = []
    n_panels = len(x_positions) - 1
    for index in range(n_panels):
        x, x_next = x_positions[index], x_positions[index + 1]
        for z, role, A in ((z_bottom, "lower_chord", 0.30 * 0.36), (z_top, "upper_chord", 0.30 * 0.36)):
            i = node_index[(round(float(x), 3), z)]
            j = node_index[(round(float(x_next), 3), z)]
            elements.append(add(role, i, j, A, float(x_next - x)))
    first, last = x_positions[0], x_positions[-1]
    for x, role in ((first, "end_post_0"), (last, "end_post_1")):
        i = node_index[(round(float(x), 3), z_bottom)]
        j = node_index[(round(float(x), 3), z_top)]
        elements.append(add(role, i, j, 0.22 * 0.25, z_top - z_bottom))
    middle = (len(x_positions) - 1) / 2.0
    for index in range(1, len(x_positions) - 1):
        x = x_positions[index]
        i = node_index[(round(float(x), 3), z_bottom)]
        j = node_index[(round(float(x), 3), z_top)]
        elements.append(add("vertical", i, j, 0.22 * 0.25, z_top - z_bottom))
    for index in range(n_panels):
        x, x_next = x_positions[index], x_positions[index + 1]
        descending = index < middle
        z_from, z_to = (z_top, z_bottom) if descending else (z_bottom, z_top)
        i = node_index[(round(float(x), 3), z_from)]
        j = node_index[(round(float(x_next), 3), z_to)]
        direction = nodes[j][0] - nodes[i][0]
        elements.append(add("diagonal", i, j, 0.24 * 0.28, float(np.hypot(direction, z_to - z_from))))
    return nodes, elements, node_index


def solve_truss_plane(nodes, elements, constrained, node_loads):
    count = len(nodes)
    fixed = {2 * node for node, kind in constrained if kind == "pin"}
    fixed |= {2 * node + 1 for node, _ in constrained}
    fixed_dofs = sorted(fixed)
    free = np.array([dof for dof in range(2 * count) if dof not in fixed_dofs], dtype=int)
    K = np.zeros((2 * count, 2 * count))
    for e in elements:
        direction = nodes[e["j"]] - nodes[e["i"]]
        unit = direction / e["L_m"]
        axial = e["E_Pa"] * e["A_m2"] / e["L_m"]
        projection = axial * np.outer(unit, unit)
        dofs = [2 * e["i"], 2 * e["i"] + 1, 2 * e["j"], 2 * e["j"] + 1]
        for a in range(4):
            for b in range(4):
                sign = 1.0 if (a // 2) == (b // 2) else -1.0
                K[dofs[a], dofs[b]] += sign * projection[a % 2, b % 2]
    F = np.zeros(2 * count)
    for node, load in node_loads.items():
        F[2 * node + 1] -= load
    for e in elements:
        weight = e["A_m2"] * e["L_m"] * e["rho"] * G
        F[2 * e["i"] + 1] -= weight / 2.0
        F[2 * e["j"] + 1] -= weight / 2.0
    displacement = np.zeros(2 * count)
    free_block = K[np.ix_(free, free)]
    displacement[free] = np.linalg.solve(free_block, F[free])
    eigenvalues = np.linalg.eigvalsh((free_block + free_block.T) / 2.0)
    smallest, largest = float(abs(eigenvalues[0])), float(abs(eigenvalues[-1]))
    condition = (largest / smallest) if smallest > 0 else float("inf")
    reactions = K @ displacement - F
    results = []
    for e in elements:
        direction = nodes[e["j"]] - nodes[e["i"]]
        unit = direction / e["L_m"]
        delta = displacement[2 * e["j"]:2 * e["j"] + 2] - displacement[2 * e["i"]:2 * e["i"] + 2]
        force = e["E_Pa"] * e["A_m2"] / e["L_m"] * float(unit @ delta)
        results.append({"name": e["name"], "role": e["role"], "N_N": force,
                        "sigma_MPa": force / (e["A_m2"] * 1e6), "A_m2": e["A_m2"]})
    support_total = sum(reactions[2 * node + 1] for node, kind in constrained)
    applied = sum(node_loads.values()) + sum(e["A_m2"] * e["L_m"] * e["rho"] * G for e in elements)
    residual = abs(support_total - applied) / max(applied, 1.0)
    return displacement, reactions, results, residual, condition


def analyze_truss(b, s, tag, start, spans, warnings):
    end = start + sum(spans)
    w = b["width"]
    count = max(4, round((end - start) / 6))
    x_positions = list(np.linspace(start, end, count + 1))
    z_bottom, z_top = -s["deck_thickness"] - 0.5, s["height"] - s["deck_thickness"] - 0.5
    plane_ys = (-0.38 * w, 0.38 * w)
    depth = z_top - z_bottom
    per_plane = []
    deck_line = ((s["deck_thickness"] * CONCRETE_RHO + b["asphalt_thickness"] * ASPHALT_RHO) * G
                 + LIVE_PA) * w / 2.0
    for sign_index, y in enumerate(plane_ys):
        plane_nodes, plane_elements, node_index = build_pratt_plane(x_positions, z_bottom, z_top, tag, sign_index)
        nodes2d = np.array(plane_nodes, dtype=float)
        start_node = node_index[(round(float(x_positions[0]), 3), z_bottom)]
        end_node = node_index[(round(float(x_positions[-1]), 3), z_bottom)]
        constrained = [(start_node, "pin"), (end_node, "roller")]
        node_loads = {}
        for index, x in enumerate(x_positions):
            left = max((point for point in x_positions if point < x), default=x)
            right = min((point for point in x_positions if point > x), default=x)
            tributary = ((x - left) + (right - x)) / 2.0
            node_loads[node_index[(round(float(x), 3), z_bottom)]] = deck_line * tributary
        displacement, reactions, results, residual, condition = solve_truss_plane(
            nodes2d, plane_elements, constrained, node_loads)
        if condition is not None:
            warnings.append(f"plane y={y:.2f}m idealization near-singular (stiffness ratio {condition:.1e})")
        support_nodes = {start_node, end_node}
        deflection, deflection_node = 0.0, None
        for node in range(len(nodes2d)):
            if node in support_nodes:
                continue
            if -displacement[2 * node + 1] > deflection:
                deflection = -displacement[2 * node + 1]
        tension = max(results, key=lambda r: r["N_N"])
        compression = min(results, key=lambda r: r["N_N"])
        per_plane.append({"plane_y_m": round(float(y), 3),
                          "max_tension": {"member": tension["name"], "kN": tension["N_N"] / 1000.0,
                                          "MPa": abs(tension["sigma_MPa"])},
                          "max_compression": {"member": compression["name"], "kN": compression["N_N"] / 1000.0,
                                              "MPa": abs(compression["sigma_MPa"])},
                          "max_deflection_mm": deflection * 1000.0,
                          "deflection_ratio": (end - start) / deflection if deflection > 0 else None,
                          "reactions_kN": [roundfloat(reactions[2 * start_node + 1]),
                                           roundfloat(reactions[2 * end_node + 1])],
                          "member_count": len(results),
                          "checks": {"vertical_reaction_residual_relative": residual,
                                     "stiffness_condition_ratio": condition}})
    steel_mass = sum(e["A_m2"] * e["L_m"] * STEEL_RHO for e in plane_elements) * 2
    deck_mass = w * (end - start) * s["deck_thickness"] * CONCRETE_RHO
    return {"tag": tag, "form": s["form"], "span_m": sum(spans),
            "status": "analyzed_plane_truss", "panel_count": count,
            "loads": {"deck_line_per_plane_N_per_m": deck_line, "planes": 2,
                      "deck_width_m": w, "deck_thickness_m": s["deck_thickness"]},
            "planes": per_plane,
            "masses_kg": {"steel_truss_per_plane": steel_mass / 2.0, "deck_concrete": deck_mass,
                          "pavement": w * (end - start) * b["asphalt_thickness"] * ASPHALT_RHO}}


def roundfloat(value):
    value = float(value)
    if abs(value) < 1e-9:
        value = 0.0
    return round(value, 1)


def analyze_girder(b, s, tag, spans, start):
    n = max(1, s["girder_count"])
    spacing = b.get("girder_spacing", b["width"] * 0.76 / max(1, n - 1))
    steel, rects = girder_rectangles(b, s, spacing)
    props = section_properties(rects)
    h = s["height"]
    tributary = b["width"] / n
    q_dead = (s["deck_thickness"] * CONCRETE_RHO + b["asphalt_thickness"] * ASPHALT_RHO) * G * tributary
    q_live = LIVE_PA * tributary
    rho = STEEL_RHO if steel else CONCRETE_RHO
    E = STEEL_E if steel else CONCRETE_E
    self_weight = props["area_m2"] * rho * G
    beam = continuous_beam(spans, q_dead + q_live + self_weight, E)
    sigma_sag = beam["max_sagging_Nm"] * max(props["c_top_m"], props["c_bottom_m"]) / props["I_m4"] / 1e6
    sigma_hog = abs(beam["max_hogging_Nm"]) * max(props["c_top_m"], props["c_bottom_m"]) / props["I_m4"] / 1e6
    L_struct = sum(spans)
    length_used = L_struct + 0.24
    masses = {"girder_total": props["area_m2"] * length_used * rho * n,
              "deck_concrete": L_struct * b["width"] * s["deck_thickness"] * CONCRETE_RHO,
              "pavement": L_struct * b["width"] * b["asphalt_thickness"] * ASPHALT_RHO}
    return {
        "tag": tag, "form": s["form"], "spans_m": spans, "girder_count": n,
        "status": "analyzed_girder_bending",
        "section": {"type": "steel_box_girder_envelope" if ("箱桁" in s["form"]) else
                    ("steel_plate_girder" if steel else "pc_rc_girder"),
                    "rectangles_m": [(round(r[0], 4), round(r[1], 4), round(r[2], 4)) for r in rects],
                    **{k: props[k] for k in ("area_m2", "I_m4", "z_centroid_m",
                                             "c_top_m", "c_bottom_m", "height_m")}},
        "loads": {"tributary_width_m": tributary,
                  "deck_dead_N_per_m": q_dead, "live_N_per_m": q_live,
                  "self_weight_N_per_m": self_weight,
                  "total_line_N_per_m": q_dead + q_live + self_weight},
        "results": {"max_sagging_kNm": beam["max_sagging_Nm"] / 1000.0,
                    "max_sagging_x_m": beam["max_sagging_x"],
                    "sagging_stress_MPa": sigma_sag,
                    "max_hogging_kNm": beam["max_hogging_Nm"] / 1000.0,
                    "max_hogging_x_m": beam["max_hogging_x"],
                    "hogging_stress_MPa": sigma_hog,
                    "max_deflection_mm": beam["max_deflection_m"] * 1000.0 if beam["max_deflection_m"] else None,
                    "deflection_ratio": beam["worst_deflection_ratio"],
                    "reactions_kN_per_girder": [roundfloat(value / 1000.0) for value in beam["reactions_N"]]},
        "main_span_m": max(spans), "masses_kg": masses}


def analyze_slab(b, s, tag, spans, start):
    solid, area, inertia = slab_strip(b, s)
    q_dead = area * CONCRETE_RHO * G + b["asphalt_thickness"] * ASPHALT_RHO * G
    q_live = LIVE_PA
    beam = continuous_beam(spans, q_dead + q_live, CONCRETE_E)
    sigma_sag = beam["max_sagging_Nm"] * (area / 2.0) / inertia / 1e6
    sigma_hog = abs(beam["max_hogging_Nm"]) * (area / 2.0) / inertia / 1e6
    L_struct = sum(spans)
    w = b["width"]
    masses = {"slab_concrete": (area if solid else area) * w * L_struct * CONCRETE_RHO,
              "pavement": L_struct * w * b["asphalt_thickness"] * ASPHALT_RHO}
    return {
        "tag": tag, "form": s["form"], "spans_m": spans,
        "status": "analyzed_slab_bending",
        "section": {"strip_area_m2_per_m": area, "strip_I_m4_per_m": inertia, "thickness_m": s["height"],
                    "hollow_void_present": not solid},
        "loads": {"strip_dead_N_per_m": q_dead, "strip_live_N_per_m": q_live},
        "results": {"max_sagging_kNm_per_m": beam["max_sagging_Nm"] / 1000.0,
                    "sagging_stress_MPa": sigma_sag,
                    "max_hogging_kNm_per_m": beam["max_hogging_Nm"] / 1000.0,
                    "hogging_stress_MPa": sigma_hog,
                    "max_deflection_mm": beam["max_deflection_m"] * 1000.0 if beam["max_deflection_m"] else None,
                    "deflection_ratio": beam["worst_deflection_ratio"],
                    "reactions_kN_per_m": [roundfloat(value / 1000.0) for value in beam["reactions_N"]]},
        "main_span_m": max(spans), "masses_kg": masses}


def analyze_structure(b, s):
    start = b["end_overhang"]
    structures = b["model_structures"]
    for previous in structures[:s["number"] - 1]:
        start += sum(previous["spans"]) + b["group_gap"]
    spans = s["spans"]
    tag = f"S{s['number']:02d}"
    warnings = []
    if "トラス" in s["form"]:
        return analyze_truss(b, s, tag, start, spans, warnings)
    integrated = "床版橋" in s["form"]
    if integrated:
        return analyze_slab(b, s, tag, spans, start)
    return analyze_girder(b, s, tag, spans, start)


def structure_values(structure):
    if structure["status"] == "analyzed_plane_truss":
        tension = []
        compression = []
        deflections = []
        ratios = []
        for plane in structure["planes"]:
            tension.append(plane["max_tension"])
            compression.append(plane["max_compression"])
            deflections.append(plane["max_deflection_mm"])
            if plane["deflection_ratio"]:
                ratios.append(plane["deflection_ratio"])
        best_t = max(tension, key=lambda r: r["kN"])
        best_c = max(compression, key=lambda r: r["kN"])
        return {"span_m": structure["span_m"],
                "text": (f"最大引張 {best_t['member']} {best_t['kN']:,.0f} kN ({best_t['MPa']:.0f} MPa) · "
                         f"最大圧縮 {best_c['member']} {best_c['kN']:,.0f} kN ({best_c['MPa']:.0f} MPa) · "
                         f"たわみ目安 {max(deflections):.1f} mm (1/{min(ratios):,.0f})" if ratios and deflections else ""),
                "max_stress_MPa": max(best_t["MPa"], best_c["MPa"])}
    results = structure["results"]
    sag, hog = results["sagging_stress_MPa"], results["hogging_stress_MPa"]
    ratio = results["deflection_ratio"]
    deflection = results["max_deflection_mm"]
    text = (f"正曲げ σ {sag:.0f} MPa · 支点負曲げ σ {hog:.0f} MPa"
            if structure["status"] == "analyzed_girder_bending" else
            f"床版並曲げ σ {sag:.0f} MPa · 支点側 σ {hog:.0f} MPa")
    if deflection and ratio:
        text += f" · たわみ {deflection:.1f} mm (1/{ratio:,.0f})"
    return {"span_m": structure["main_span_m"], "text": text,
            "max_stress_MPa": max(sag, hog)}


def analyze_bridge(directory):
    b = json.loads((directory / "parameters.json").read_text(encoding="utf-8"))
    structures = [analyze_structure(b, s) for s in b["model_structures"]]
    deck_mass = 0.0
    girder_mass = 0.0
    pavement_mass = 0.0
    truss_mass = 0.0
    for structure in structures:
        masses = structure.get("masses_kg", {})
        girder_mass += masses.get("girder_total", 0.0) + masses.get("steel_truss_per_plane", 0.0) * 2
        truss_mass += masses.get("steel_truss_per_plane", 0.0) * 2 if "steel_truss_per_plane" in masses else 0.0
        deck_mass += masses.get("deck_concrete", 0.0) + masses.get("slab_concrete", 0.0)
        pavement_mass += masses.get("pavement", 0.0)
    entries = [structure_values(s) for s in structures]
    worst = max(entries, key=lambda e: e["max_stress_MPa"]) if entries else None
    ratios = []
    for structure in structures:
        results = structure.get("results") or {}
        if results.get("deflection_ratio"):
            ratios.append(results["deflection_ratio"])
        for plane in structure.get("planes", []):
            if plane.get("deflection_ratio"):
                ratios.append(plane["deflection_ratio"])
    summary = {
        "structure_count": len(structures),
        "statuses": sorted({s["status"] for s in structures}),
        "max_stress_MPa": worst["max_stress_MPa"] if worst else None,
        "worst_structure": worst["text"] if worst else None,
        "min_deflection_ratio": min(ratios) if ratios else None,
    }
    result = {"schema": "karte.structural_screening/1", "bridge_id": b["id"], "name": b["name"],
              "classification": b["classification"],
              "analysis_scope": " screening indicators with stated assumptions; not design verification",
              "assumptions": ASSUMPTIONS,
              "structures": structures, "summary": summary,
              "masses_kg": {"steel_girders_truss": girder_mass, "deck_concrete": deck_mass,
                            "pavement": pavement_mass}}
    (directory / "structural.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    row = {"id": b["id"], "name": b["name"], "length_m": b["length"], "width_m": b["width"],
           "structure_count": len(structures), "statuses": summary["statuses"],
           "max_stress_MPa": summary["max_stress_MPa"],
           "min_deflection_ratio": summary["min_deflection_ratio"],
           "worst_structure": summary["worst_structure"]}
    return row


def self_check():
    EI, q = 1e10, 1000.0
    beam = continuous_beam([10.0], q, EI)
    assert abs(beam["reactions_N"][0] - 5000.0) < 1e-6, beam["reactions_N"]
    assert abs(beam["max_sagging_Nm"] - 12500.0) < 1e-3
    assert abs(beam["max_deflection_m"] - 1.302e-5) < 1e-8, beam["max_deflection_m"]
    beam = continuous_beam([10.0, 10.0], q, EI)
    assert abs(beam["reactions_N"][0] - 3750.0) < 1e-6
    assert abs(beam["reactions_N"][1] - 12500.0) < 1e-6
    assert abs(beam["max_hogging_Nm"] + 12500.0) < 1e-3
    assert abs(beam["max_sagging_Nm"] - 9 * q * 100 / 128.0) < 10.0, beam["max_sagging_Nm"]


def main():
    self_check()
    rows = []
    for directory in sorted((OUT / "models").iterdir()):
        if not (directory / "parameters.json").is_file():
            continue
        row = analyze_bridge(directory)
        rows.append(row)
        print(f"{row['id']}: {row['statuses']} σmax={row['max_stress_MPa']:.0f}MPa "
              f"L/δ={row['min_deflection_ratio']:.0f}", flush=True)
    (OUT / "structural_summary.json").write_text(
        json.dumps({"schema": "karte.structural_screening_summary/1", "case_count": len(rows),
                    "cases": rows,
                    "method": "CAD包絡断面による連続梁/中空床版帯/2面トラスの簡妥スクリーニング。仮定は各structural.jsonのassumptionsを参照",
                    "scope": "Screening indicators, not design verification"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cases: {len(rows)}")


if __name__ == "__main__":
    sys.exit(main())
