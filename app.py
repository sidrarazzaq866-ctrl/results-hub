import io, uuid
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import find_peaks, peak_widths, savgol_filter
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

st.set_page_config(page_title="Results Hub", page_icon="🔬", layout="wide")
st.markdown("<style>#MainMenu,footer{visibility:hidden}</style>", unsafe_allow_html=True)
plt.rcParams.update({"font.family": "serif", "font.size": 11, "axes.linewidth": 1.1,
                     "xtick.direction": "in", "ytick.direction": "in"})
if "report" not in st.session_state:
    st.session_state.report = []

TYPES = ["csv", "txt", "dat", "xy", "xlsx", "xls"]

# ---------- helpers ----------
def load(f):
    if f.name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(f, header=None)
    else:
        raw = f.getvalue().decode("utf-8", "ignore")
        try:
            df = pd.read_csv(io.StringIO(raw), sep=None, engine="python", header=None)
        except Exception:
            df = pd.read_csv(io.StringIO(raw), sep=r"\s+", engine="python", header=None, on_bad_lines="skip")
    df = df.apply(pd.to_numeric, errors="coerce").dropna(how="all").dropna(axis=1, how="all").dropna()
    df.columns = [f"Column {i+1}" for i in range(df.shape[1])]
    return df.reset_index(drop=True)

def png(fig):
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=300, bbox_inches="tight")
    return b.getvalue()

def fig_buttons(fig, name, cap, key):
    data = png(fig)
    a, b = st.columns(2)
    a.download_button("⬇ PNG (300 dpi)", data, f"{name}.png", "image/png", key=key + "d")
    if b.button("➕ Add figure to report", key=key + "a"):
        st.session_state.report.append({"id": uuid.uuid4().hex, "kind": "fig", "cap": cap, "png": data})
        st.toast("Added to report")
    plt.close(fig)

def table_buttons(df, name, cap, key):
    a, b = st.columns(2)
    a.download_button("⬇ CSV", df.to_csv(index=False), f"{name}.csv", "text/csv", key=key + "d")
    if b.button("➕ Add table to report", key=key + "a"):
        st.session_state.report.append({"id": uuid.uuid4().hex, "kind": "tab", "cap": cap, "df": df})
        st.toast("Added to report")

def pick(df, label, i):
    return st.selectbox(label, list(df.columns), min(i, len(df.columns) - 1))

# ---------- XRD ----------
SPINEL = [(1,1,1),(2,2,0),(3,1,1),(2,2,2),(4,0,0),(3,3,1),(4,2,2),(5,1,1),(4,4,0),(5,3,1),(6,2,0),(5,3,3),(6,2,2)]

def xrd_tab():
    up = st.file_uploader("XRD file (2θ and intensity)", type=TYPES, key="xrd")
    if not up:
        st.info("Upload a two-column file: 2θ (degrees) and intensity.")
        return
    df = load(up)
    c1, c2 = st.columns(2)
    xc, yc = pick(df, "2θ column", 0), pick(df, "Intensity column", 1)
    s1, s2, s3, s4, s5 = st.columns(5)
    lam = s1.number_input("Wavelength λ (Å)", value=1.5406, format="%.4f")
    K = s2.number_input("Scherrer K", value=0.9)
    inst = s3.number_input("Instrument FWHM (°)", value=0.0, help="Subtract instrument broadening using a standard such as LaB6 or Si.")
    prom = s4.slider("Peak sensitivity (%)", 1, 50, 5)
    win = s5.slider("Smoothing", 1, 21, 5, step=2)
    a0 = st.number_input("Approx. lattice parameter for auto-labelling hkl (Å)", value=8.44)

    o = np.argsort(df[xc].values)
    x, y = df[xc].values[o].astype(float), df[yc].values[o].astype(float)
    ys = savgol_filter(y, win, 2) if win >= 5 and len(y) > win else y
    step = np.median(np.diff(x))
    pk, _ = find_peaks(ys, prominence=prom / 100 * (ys.max() - ys.min()), distance=max(1, int(0.3 / step)))
    if len(pk) == 0:
        st.warning("No peaks found. Lower the sensitivity.")
        return
    fwhm = peak_widths(ys, pk, rel_height=0.5)[0] * step
    th = np.radians(x[pk] / 2)
    beta = np.radians(np.sqrt(np.maximum(fwhm**2 - inst**2, 0)))
    D = np.where(beta > 0, K * lam / (np.where(beta > 0, beta, 1) * np.cos(th)) / 10, np.nan)
    d = lam / (2 * np.sin(th))
    pred = [(f"{h}{k}{l}", 2 * np.degrees(np.arcsin(lam / (2 * a0 / np.sqrt(h*h+k*k+l*l)))))
            for h, k, l in SPINEL if lam / (2 * a0 / np.sqrt(h*h+k*k+l*l)) < 1]
    hkl = []
    for p in x[pk]:
        best = min(pred, key=lambda t: abs(t[1] - p))
        hkl.append(best[0] if abs(best[1] - p) < 0.6 else "")
    peaks = pd.DataFrame({"2θ (°)": x[pk].round(3), "hkl": hkl, "d (Å)": d.round(4),
                          "FWHM (°)": fwhm.round(4), "D (nm)": np.round(D, 2)})
    st.caption("hkl labels are only suggestions from the lattice parameter above. Check them against your JCPDS card and edit if needed.")
    ed = st.data_editor(peaks, hide_index=True, disabled=["2θ (°)", "d (Å)", "FWHM (°)", "D (nm)"])

    def a_from(s, dd):
        s = str(s).strip()
        return dd * np.sqrt(sum(int(ch)**2 for ch in s)) if s.isdigit() else np.nan
    res = ed.copy()
    res["a (Å)"] = [round(a_from(s, dd), 4) for s, dd in zip(ed["hkl"], d)]
    m1, m2 = st.columns(2)
    m1.metric("Mean crystallite size (Scherrer)", f"{np.nanmean(D):.1f} nm")
    if res["a (Å)"].notna().any():
        m2.metric("Mean lattice parameter a", f"{res['a (Å)'].mean():.4f} ± {res['a (Å)'].std():.4f} Å")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, color="#1f3b57", lw=1)
    for p, h in zip(pk, ed["hkl"]):
        ax.plot(x[p], ys[p], "v", color="#c0504d", ms=4)
        if str(h).strip():
            ax.annotate(f"({h})", (x[p], ys[p]), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=8)
    ax.set_xlabel("2θ (degrees)"); ax.set_ylabel("Intensity (a.u.)")
    st.pyplot(fig)
    fig_buttons(fig, "xrd_pattern", "XRD pattern of the sample with indexed reflections.", "x1")
    st.dataframe(res, hide_index=True)
    table_buttons(res, "xrd_results", "XRD peak positions, d-spacing, FWHM, crystallite size and lattice parameter.", "x2")

    ok = beta > 0
    if ok.sum() >= 3:
        X, Y = 4 * np.sin(th[ok]), beta[ok] * np.cos(th[ok])
        sl, ic = np.polyfit(X, Y, 1)
        fig2, ax2 = plt.subplots(figsize=(5, 3.6))
        ax2.plot(X, Y, "o", color="#1f3b57"); ax2.plot(X, sl * X + ic, "-", color="#c0504d")
        ax2.set_xlabel("4 sin θ"); ax2.set_ylabel("β cos θ (rad)")
        txt = f"Strain ε = {sl:.2e}"
        if ic > 0:
            txt += f", D = {K * lam / ic / 10:.1f} nm"
        st.markdown("**Williamson-Hall:** " + txt)
        st.pyplot(fig2)
        fig_buttons(fig2, "williamson_hall", "Williamson-Hall plot. " + txt + ".", "x3")

# ---------- VSM ----------
def crossings(a, b):
    out = []
    for i in range(len(a) - 1):
        if a[i] == 0:
            out.append(b[i])
        elif a[i] * a[i+1] < 0:
            t = a[i] / (a[i] - a[i+1])
            out.append(b[i] + t * (b[i+1] - b[i]))
    return out

def vsm_tab():
    ups = st.file_uploader("VSM files (H and M). Upload one file per sample.", type=TYPES, accept_multiple_files=True, key="vsm")
    if not ups:
        st.info("Upload files with the field in the first column and magnetization in the second. Keep the points in measured order.")
        return
    u1, u2 = st.columns(2)
    hu = u1.text_input("Field unit", "Oe"); mu = u2.text_input("Magnetization unit", "emu/g")
    rows, data = [], []
    for f in ups:
        df = load(f)
        H, M = df.iloc[:, 0].values.astype(float), df.iloc[:, 1].values.astype(float)
        name = f.name.rsplit(".", 1)[0]
        Ms = np.mean(np.abs(M[np.abs(H) >= 0.9 * np.abs(H).max()]))
        mr, hc = crossings(H, M), crossings(M, H)
        Mr = np.mean(np.abs(mr)) if mr else np.nan
        Hc = np.mean(np.abs(hc)) if hc else np.nan
        area = abs(np.sum((M[1:] + M[:-1]) / 2 * np.diff(H)))
        rows.append({"Sample": name, f"Ms ({mu})": round(Ms, 4), f"Mr ({mu})": round(Mr, 4),
                     f"Hc ({hu})": round(Hc, 3), "Mr/Ms": round(Mr / Ms, 4), f"Loop area ({hu}·{mu})": round(area, 3)})
        data.append((name, H, M))
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for n, H, M in data:
        ax.plot(H, M, lw=1.4, label=n)
    ax.axhline(0, color="gray", lw=.6); ax.axvline(0, color="gray", lw=.6)
    ax.set_xlabel(f"Applied field H ({hu})"); ax.set_ylabel(f"Magnetization M ({mu})")
    if len(data) > 1:
        ax.legend(frameon=False)
    allH = np.concatenate([h for _, h, _ in data])
    lo, hi = float(allH.min()), float(allH.max())
    if hi > lo:
        r = st.slider("Zoom the field range", lo, hi, (lo, hi))
        ax.set_xlim(r)
    st.pyplot(fig)
    fig_buttons(fig, "mh_loop", "Room-temperature M-H hysteresis loops.", "v1")
    res = pd.DataFrame(rows)
    st.dataframe(res, hide_index=True)
    table_buttons(res, "vsm_results", "Magnetic parameters extracted from the M-H loops.", "v2")
    st.caption("Ms is the average |M| in the top 10% of the field range. Loop area is only meaningful for a closed loop.")

# ---------- Dielectric ----------
def diel_tab():
    up = st.file_uploader("Dielectric file (frequency, capacitance or ε′, tan δ)", type=TYPES, key="di")
    if not up:
        st.info("Upload a file with frequency, capacitance (or ε′) and tan δ columns.")
        return
    df = load(up)
    mode = st.radio("Your file has", ["Capacitance and tan δ", "ε′ and tan δ"], horizontal=True)
    a, b, c = st.columns(3)
    fc = a.selectbox("Frequency column", list(df.columns), 0)
    vc = b.selectbox("Capacitance / ε′ column", list(df.columns), min(1, df.shape[1] - 1))
    tc = c.selectbox("tan δ column", list(df.columns), min(2, df.shape[1] - 1))
    e0 = 8.854e-12
    f, v, tand = df[fc].values.astype(float), df[vc].values.astype(float), df[tc].values.astype(float)
    if mode.startswith("Cap"):
        g1, g2, g3 = st.columns(3)
        t = g1.number_input("Thickness (mm)", value=1.0) / 1000
        dia = g2.number_input("Pellet diameter (mm)", value=10.0) / 1000
        unit = {"F": 1, "nF": 1e-9, "pF": 1e-12}[g3.selectbox("Capacitance unit", ["pF", "nF", "F"])]
        e1 = v * unit * t / (e0 * np.pi * (dia / 2) ** 2)
    else:
        e1 = v
    e2 = e1 * tand
    sig = 2 * np.pi * f * e0 * e1 * tand
    out = pd.DataFrame({"f (Hz)": f, "ε′": e1, "ε″": e2, "tan δ": tand, "σac (S/m)": sig})
    which = st.selectbox("Plot", ["ε′ vs frequency", "tan δ vs frequency", "σac vs frequency", "Cole-Cole (ε″ vs ε′)"])
    fig, ax = plt.subplots(figsize=(5.5, 4))
    if which.startswith("ε′"):
        ax.semilogx(f, e1, "o-", ms=3); ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Dielectric constant ε′")
    elif which.startswith("tan"):
        ax.semilogx(f, tand, "o-", ms=3); ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Loss tangent tan δ")
    elif which.startswith("σ"):
        ax.loglog(f, sig, "o-", ms=3); ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("σac (S/m)")
    else:
        ax.plot(e1, e2, "o-", ms=3); ax.set_xlabel("ε′"); ax.set_ylabel("ε″")
    st.pyplot(fig)
    fig_buttons(fig, "dielectric", f"Dielectric analysis: {which}.", "d1")
    st.dataframe(out, hide_index=True)
    st.download_button("⬇ Full results CSV", out.to_csv(index=False), "dielectric_results.csv", "text/csv")

# ---------- FTIR ----------
REF = pd.DataFrame([
    ["3200-3600", "O-H stretching (adsorbed water)"], ["~2850-2950", "C-H stretching (organic residue, PEEK)"],
    ["~1650", "C=O stretching (PEEK ketone)"], ["~1630", "H-O-H bending (water)"],
    ["~1595 and ~1490", "Aromatic C=C (PEEK)"], ["~1380", "Residual nitrate (sol-gel)"],
    ["~1190-1220", "Aryl ether C-O-C (PEEK)"], ["540-600", "M-O stretching, tetrahedral site (spinel ferrite)"],
    ["380-450", "M-O stretching, octahedral site (spinel ferrite)"]], columns=["Wavenumber (cm⁻¹)", "Typical assignment"])

def ftir_tab():
    up = st.file_uploader("FTIR file (wavenumber and signal)", type=TYPES, key="ft")
    if not up:
        st.info("Upload a file with wavenumber and transmittance or absorbance.")
        return
    df = load(up)
    a, b, c = st.columns(3)
    xc, yc = a.selectbox("Wavenumber column", list(df.columns), 0), b.selectbox("Signal column", list(df.columns), min(1, df.shape[1] - 1))
    mode = c.radio("Signal type", ["Transmittance", "Absorbance"], horizontal=True)
    prom = st.slider("Peak sensitivity (%)", 1, 50, 8)
    x, y = df[xc].values.astype(float), df[yc].values.astype(float)
    sig = -y if mode == "Transmittance" else y
    pk, _ = find_peaks(sig, prominence=prom / 100 * (sig.max() - sig.min()))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, color="#1f3b57", lw=1)
    for p in pk:
        ax.annotate(f"{x[p]:.0f}", (x[p], y[p]), xytext=(0, -10 if mode == "Transmittance" else 6),
                    textcoords="offset points", ha="center", fontsize=7, rotation=90)
    ax.invert_xaxis(); ax.set_xlabel("Wavenumber (cm⁻¹)"); ax.set_ylabel(mode + " (a.u.)")
    st.pyplot(fig)
    fig_buttons(fig, "ftir", "FTIR spectrum of the sample.", "f1")
    tab = pd.DataFrame({"Wavenumber (cm⁻¹)": x[pk].round(1), "Signal": y[pk].round(3)})
    st.dataframe(tab, hide_index=True)
    table_buttons(tab, "ftir_peaks", "FTIR peak positions.", "f2")
    with st.expander("Typical band ranges (check these against the papers you cite)"):
        st.dataframe(REF, hide_index=True)

# ---------- Report ----------
def build_docx():
    doc = Document()
    doc.add_heading("Results", 1)
    fi = ti = 0
    for it in st.session_state.report:
        if it["kind"] == "fig":
            fi += 1
            doc.add_picture(io.BytesIO(it["png"]), width=Inches(5.6))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run(f"Figure {fi}. ").bold = True; p.add_run(it["cap"])
        else:
            ti += 1
            p = doc.add_paragraph(); p.add_run(f"Table {ti}. ").bold = True; p.add_run(it["cap"])
            df = it["df"]
            t = doc.add_table(rows=1, cols=len(df.columns)); t.style = "Table Grid"
            for i, col in enumerate(df.columns):
                t.rows[0].cells[i].text = str(col)
            for _, r in df.iterrows():
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    cells[i].text = f"{v:.5g}" if isinstance(v, (float, np.floating)) else str(v)
            doc.add_paragraph()
    b = io.BytesIO(); doc.save(b)
    return b.getvalue()

def report_tab():
    rep = st.session_state.report
    if not rep:
        st.info("Nothing here yet. Click 'Add to report' under any figure or table.")
        return
    for it in list(rep):
        c1, c2 = st.columns([6, 1])
        icon = "🖼" if it["kind"] == "fig" else "📋"
        it["cap"] = c1.text_input(f"{icon} Caption", it["cap"], key="cap" + it["id"])
        if c2.button("🗑", key="rm" + it["id"]):
            rep.remove(it)
            st.rerun()
        if it["kind"] == "fig":
            st.image(it["png"], width=380)
    st.download_button("⬇ Download Word report", build_docx(), "Results_Report.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.title("🔬 Results Hub")
st.caption("Upload your measured data, get the analysis and thesis-ready figures. Always check the results against your instrument software and describe your method in the thesis.")
t1, t2, t3, t4, t5 = st.tabs(["XRD", "VSM / Hysteresis", "Dielectric", "FTIR", "📄 Report"])
with t1: xrd_tab()
with t2: vsm_tab()
with t3: diel_tab()
with t4: ftir_tab()
with t5: report_tab()
