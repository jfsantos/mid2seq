/**
 * scspdspasm.js — SCSP/Sega Saturn DSP assembler (JavaScript port)
 *
 * Port of scspdspasm.py v0.3 for in-browser use with the Saturn tracker.
 * Assembles USC (micro-source) text into MPRO/COEF/MADRS arrays that can
 * be loaded directly into the SCSP WASM emulator via scsp_dsp_load_arrays().
 *
 * Usage:
 *   const result = scspdspAssemble(uscText, { rbl: 1 });
 *   // result.mpro   — Uint16Array(512)  [128 steps × 4 words]
 *   // result.coef   — Int16Array(64)
 *   // result.madrs  — Uint16Array(32)
 *   // result.rbl    — 0-3
 *   // result.errors — string[] (empty on success)
 *   // result.steps  — number of active MPRO steps
 */

// ─── Numeric helpers ────────────────────────────────────────────────

function twosComp13(value) {
    if (value < -4096 || value > 4095)
        throw new Error('Coefficient out of range (-4096..4095)');
    if (value < 0) value = (1 << 13) + value;
    return value & 0x1FFF;
}

function parseCoefRhs(s) {
    s = s.trim();
    if (s.toUpperCase().startsWith('&H'))
        return parseInt(s.slice(2), 16) & 0x1FFF;
    if (s.startsWith('%')) {
        const pct = parseFloat(s.slice(1));
        let v = Math.round(4095.0 * (pct / 100.0));
        v = Math.min(Math.max(v, -4096), 4095);
        return twosComp13(v);
    }
    if (s.includes('.')) {
        const f = parseFloat(s);
        return twosComp13(Math.round(4096.0 * f));
    }
    return twosComp13(parseInt(s, 10));
}

function parseAdrsRhs(s) {
    s = s.trim();
    if (s.toUpperCase().startsWith('&H'))
        return parseInt(s.slice(2), 16) & 0xFFFF;
    if (s.toLowerCase().startsWith('ms')) {
        const ms = parseFloat(s.slice(2));
        return Math.round(44100.0 * (ms / 1000.0)) & 0xFFFF;
    }
    return parseInt(s, 10) & 0xFFFF;
}

// ─── Symbol table ───────────────────────────────────────────────────

class Symbols {
    constructor() {
        this.coefOrder = ['ZERO'];
        this.coef = { ZERO: 0 };
        this.adrsOrder = [];
        this.adrs = {};
    }

    addCoef(name, rhs) {
        if (name.toUpperCase() === 'ZERO')
            throw new Error('ZERO is reserved');
        this.coef[name] = parseCoefRhs(rhs);
        this.coefOrder.push(name);
    }

    addAdrs(name, rhs) {
        this.adrs[name] = parseAdrsRhs(rhs);
        this.adrsOrder.push(name);
    }

    coefIndex(name) {
        const i = this.coefOrder.indexOf(name);
        if (i < 0) throw new Error(`Undefined coefficient symbol '${name}'`);
        return i;
    }

    adrsIndex(name) {
        const i = this.adrsOrder.indexOf(name);
        if (i < 0) throw new Error(`Undefined address symbol '${name}'`);
        return i;
    }
}

// ─── Instruction helpers ────────────────────────────────────────────

/** True if a packed MPRO word-quad accesses external memory (MRD or MWT). */
function instrAccessesMem(words) {
    // w1 (index 2) bit layout: MWT<<14 | MRD<<13
    return (words[2] & 0x6000) !== 0;
}

// ─── Micro-instruction encoder ──────────────────────────────────────
// Returns [w3, w2, w1, w0] (4 × uint16, big-endian word order)
// matching the MPRO layout in the SCSPDSP struct.

function packMpro(f) {
    // Build as two 32-bit halves to avoid 64-bit issues.
    // Bit layout (MSB first):
    //   63-56: TRA(7)   55: TWT   54-48: TWA(7)   47: XSEL
    //   46-45: YSEL(2)  44-39: IRA(6)   38-37: IWT,IWA split...
    // Upper 32 bits (words 3,2):
    //   w3 = bits [63:48], w2 = bits [47:32]
    // Lower 32 bits (words 1,0):
    //   w1 = bits [31:16], w0 = bits [15:0]

    const TRA   = (f.TRA   || 0) & 0x7F;
    const TWT   = (f.TWT   || 0) & 1;
    const TWA   = (f.TWA   || 0) & 0x7F;
    const XSEL  = (f.XSEL  || 0) & 1;
    const YSEL  = (f.YSEL  || 0) & 3;
    const IRA   = (f.IRA   || 0) & 0x3F;
    const IWT   = (f.IWT   || 0) & 1;
    const IWA   = (f.IWA   || 0) & 0x1F;
    const TABLE = (f.TABLE || 0) & 1;
    const MWT   = (f.MWT   || 0) & 1;
    const MRD   = (f.MRD   || 0) & 1;
    const EWT   = (f.EWT   || 0) & 1;
    const EWA   = (f.EWA   || 0) & 0xF;
    const ADRL  = (f.ADRL  || 0) & 1;
    const FRCL  = (f.FRCL  || 0) & 1;
    const SHFT  = (f.SHFT  || 0) & 3;
    const YRL   = (f.YRL   || 0) & 1;
    const NEGB  = (f.NEGB  || 0) & 1;
    const ZERO  = (f.ZERO  || 0) & 1;
    const BSEL  = (f.BSEL  || 0) & 1;
    const CRA   = (f.CRA   || 0) & 0x3F;
    const NOFL  = (f.NOFL  || 0) & 1;
    const MASA  = (f.MASA  || 0) & 0x1F;
    const ADREB = (f.ADREB || 0) & 1;
    const NXADR = (f.NXADR || 0) & 1;

    // Word 3 (bits 63:48): TRA[6:0]<<8 | TWT<<7 | TWA[6:0]
    const w3 = (TRA << 8) | (TWT << 7) | TWA;
    // Word 2 (bits 47:32): XSEL<<15 | YSEL<<13 | IRA<<6 | IWT<<5 | IWA[4:0]
    const w2 = (XSEL << 15) | (YSEL << 13) | (IRA << 6) | (IWT << 5) | IWA;
    // Word 1 (bits 31:16): TABLE<<15 | MWT<<14 | MRD<<13 | EWT<<12 | EWA<<8 |
    //                       ADRL<<7 | FRCL<<6 | SHFT<<4 | YRL<<3 | NEGB<<2 | ZERO<<1 | BSEL
    const w1 = (TABLE << 15) | (MWT << 14) | (MRD << 13) | (EWT << 12) |
               (EWA << 8) | (ADRL << 7) | (FRCL << 6) | (SHFT << 4) |
               (YRL << 3) | (NEGB << 2) | (ZERO << 1) | BSEL;
    // Word 0 (bits 15:0): CRA<<9 | NOFL<<8 | MASA<<2 | ADREB<<1 | NXADR
    // But CRA is 6 bits at [14:9], so CRA<<9 can go up to bit 14.
    const w0 = (CRA << 9) | (NOFL << 8) | (MASA << 2) | (ADREB << 1) | NXADR;

    return [w3 & 0xFFFF, w2 & 0xFFFF, w1 & 0xFFFF, w0 & 0xFFFF];
}

/** Packed NOP instruction words. */
const NOP_PACKED = packMpro({ BSEL: 1, YSEL: 1, CRA: 0, SHFT: 0 });

// ─── Input source helpers ───────────────────────────────────────────

const SRC_RE = /^(MEMS|MIXS|EXTS)(\d+)$/i;

function iraForSrc(src) {
    const m = src.match(SRC_RE);
    if (!m) throw new Error(`Bad INPUT source '${src}'`);
    const bank = m[1].toUpperCase();
    const idx = parseInt(m[2], 10);
    if (bank === 'MEMS') { if (idx < 0 || idx > 31) throw new Error('MEMS index 0..31'); return idx; }
    if (bank === 'MIXS') { if (idx < 0 || idx > 15) throw new Error('MIXS index 0..15'); return 0x20 + idx; }
    if (bank === 'EXTS') { if (idx < 0 || idx > 1)  throw new Error('EXTS index 0..1');  return 0x30 + idx; }
}

function shftForStore(opt) {
    if (!opt) return [0, true];
    const o = opt.toUpperCase();
    if (o === 'S1') return [1, true];
    if (o === 'S2') return [2, false];
    if (o === 'S3') return [3, false];
    throw new Error('Invalid store option (use S1/S2/S3 or omit)');
}

// ─── Regex patterns ─────────────────────────────────────────────────

const COEF_RE = /^\s*([A-Za-z][A-Za-z0-9]{0,14})\s*=\s*(.+?)\s*$/;
const LDI_RE  = /^\s*LDI\s+(MEMS(\d{1,2})),\s*MR\[(.+?)\]\s*$/i;
const LDY_RE  = /^\s*LDY\s+(MEMS\d{1,2}|MIXS\d{1,2}|EXTS\d)\s*$/i;
const LDA_RE  = /^\s*LDA\s+(MEMS\d{1,2}|MIXS\d{1,2}|EXTS\d)\s*$/i;
const MW_RE   = /^\s*MW\s+MR\[(.+?)\]\s*$/i;
const AT_RE   = /^\s*@\s*(.+?)\s*$/;
const ST_RE   = /^\s*>\s*([Ss][123])?\s*(.+?)\s*$/;
const MR_RE   = /^\s*MR\s+MR\[(.+?)\]\s*$/i;
const IW_RE   = /^\s*IW\s+MEMS(\d{1,2})\s*$/i;

const PROD_RE = /\b(INPUT|TEMP\d{1,2}|MEMS\d{1,2}|MIXS\d{1,2}|EXTS\d)\b\s*\*\s*(COEF\[[^\]]+\]|YREGH|YREGL|[A-Za-z][A-Za-z0-9]{0,14})/gi;

// ─── Address expression parser ──────────────────────────────────────

function parseAddrExpr(expr, syms) {
    expr = expr.trim().split("'")[0];
    const parts = expr.split('/');
    const body = parts[0].replace(/ /g, '');
    const flags = parts[1] || '';
    const elems = body.split('+');
    if (!elems.length || !/^[A-Za-z]/.test(elems[0]))
        throw new Error("MR[...] must start with an address symbol");
    const sym = elems[0];
    const masa = syms.adrsIndex(sym);
    let DEC = 0, ADREG = 0, plus1 = 0;
    for (let i = 1; i < elems.length; i++) {
        const eu = elems[i].toUpperCase();
        if (eu === 'DEC') DEC = 1;
        else if (eu === 'ADREG' || eu === 'ADRS') ADREG = 1;
        else if (elems[i] === '1') plus1 = 1;
        else if (elems[i] === '') continue;
        else throw new Error(`Unknown address element '+${elems[i]}'`);
    }
    const NOFL = flags.toUpperCase().includes('NF') ? 1 : 0;
    const TABLE = DEC ? 0 : 1;
    return { masa, TABLE, ADREB: ADREG, NXADR: plus1, NOFL };
}

// ─── Coefficient / multiplicand helpers ─────────────────────────────

function coefRefToFields(pc, syms) {
    pc = pc.trim();
    const pcu = pc.toUpperCase();
    if (pcu === 'YREGH') return { YSEL: 2, CRA: 0 };
    if (pcu === 'YREGL') return { YSEL: 3, CRA: 0 };
    if (pcu.startsWith('COEF[') && pc.endsWith(']')) {
        const name = pc.slice(5, -1);
        return { YSEL: 1, CRA: syms.coefIndex(name) & 0x3F };
    }
    if (/^[A-Za-z][A-Za-z0-9]{0,14}$/.test(pc))
        return { YSEL: 1, CRA: syms.coefIndex(pc) & 0x3F };
    throw new Error(`Bad coefficient reference '${pc}'`);
}

function multiplicandToFields(pm) {
    const pmu = pm.toUpperCase();
    if (pmu === 'INPUT') return { XSEL: 1 };
    const tm = pmu.match(/^TEMP(\d{1,2})$/);
    if (tm) return { XSEL: 0, TRA: parseInt(tm[1], 10) };
    if (/^(MEMS\d{1,2}|MIXS\d{1,2}|EXTS\d)$/.test(pmu))
        return { XSEL: 1, IRA: iraForSrc(pmu) };
    throw new Error(`Bad multiplicand '${pm}'`);
}

function expandProducts(expr, syms) {
    const prods = [];
    PROD_RE.lastIndex = 0;
    let m;
    while ((m = PROD_RE.exec(expr)) !== null) {
        const pmf = multiplicandToFields(m[1]);
        const yf = coefRefToFields(m[2], syms);
        prods.push([pmf, yf]);
    }
    if (!prods.length)
        throw new Error("No product terms found in '@' expression");
    return prods;
}

// ─── Assembler ──────────────────────────────────────────────────────

class Assembler {
    constructor() {
        this.syms = new Symbols();
        this.progWords = [];  // each entry: [w3, w2, w1, w0]
    }

    assemble(text) {
        let section = null;
        for (const raw of text.split('\n')) {
            const stripped = raw.trimStart();
            if (!stripped) continue;
            if (stripped.startsWith("'") || stripped.startsWith(')')) continue;
            const line = raw.split("'")[0].trimEnd();
            if (!line.trim()) continue;

            const u = line.trim().toUpperCase();
            if (u === '#COEF')              { section = 'COEF'; continue; }
            if (u === '#ADRS')              { section = 'ADRS'; continue; }
            if (u === '#PROG')              { section = 'PROG'; continue; }
            if (u === '#END' || u === '=END') { section = 'END';  continue; }

            if (section === 'COEF') {
                const m = line.match(COEF_RE);
                if (!m) throw new Error(`Bad coef line: ${line}`);
                this.syms.addCoef(m[1], m[2]);
                continue;
            }
            if (section === 'ADRS') {
                const m = line.match(COEF_RE);  // same pattern
                if (!m) throw new Error(`Bad adrs line: ${line}`);
                this.syms.addAdrs(m[1], m[2]);
                continue;
            }
            if (section === 'PROG') {
                this._emitInstr(line);
                continue;
            }
        }
    }

    _emitInstr(line) {
        const trimmed = line.trim();
        const upper = trimmed.toUpperCase();

        // NOP
        if (upper === 'NOP') {
            this.progWords.push(packMpro({ BSEL: 1, YSEL: 1, CRA: 0, SHFT: 0 }));
            return;
        }
        // @ with inline > store
        if (trimmed.startsWith('@') && trimmed.includes('>')) {
            const [atPart, storePart] = trimmed.split('>', 2);
            this._emitAtChain(atPart);
            this._emitStoreSuffix(storePart.trim());
            return;
        }
        // @ chain
        if (trimmed.startsWith('@')) {
            this._emitAtChain(trimmed);
            return;
        }
        // LDI
        let m = line.match(LDI_RE);
        if (m) {
            const memIdx = parseInt(m[2], 10);
            const a = parseAddrExpr(m[3], this.syms);
            this.progWords.push(packMpro({
                MRD: 1, IWT: 1, IWA: memIdx & 0x1F,
                MASA: a.masa & 0x1F, TABLE: a.TABLE,
                ADREB: a.ADREB, NXADR: a.NXADR, NOFL: a.NOFL,
            }));
            return;
        }
        // MR MR[...]
        m = line.match(MR_RE);
        if (m) {
            const a = parseAddrExpr(m[1], this.syms);
            this.progWords.push(packMpro({
                MRD: 1, MASA: a.masa & 0x1F, TABLE: a.TABLE,
                ADREB: a.ADREB, NXADR: a.NXADR, NOFL: a.NOFL,
            }));
            return;
        }
        // IW MEMS##
        m = line.match(IW_RE);
        if (m) {
            this.progWords.push(packMpro({ IWT: 1, IWA: parseInt(m[1], 10) & 0x1F }));
            return;
        }
        // MW MR[...]
        m = line.match(MW_RE);
        if (m) {
            const a = parseAddrExpr(m[1], this.syms);
            this.progWords.push(packMpro({
                MWT: 1, SHFT: 0, BSEL: 1, YSEL: 1, CRA: 0,
                MASA: a.masa & 0x1F, TABLE: a.TABLE,
                ADREB: a.ADREB, NXADR: a.NXADR, NOFL: a.NOFL,
            }));
            return;
        }
        // LDY
        m = line.match(LDY_RE);
        if (m) {
            this.progWords.push(packMpro({ IRA: iraForSrc(m[1].toUpperCase()), YRL: 1 }));
            return;
        }
        // LDA
        m = line.match(LDA_RE);
        if (m) {
            this.progWords.push(packMpro({ IRA: iraForSrc(m[1].toUpperCase()), ADRL: 1, SHFT: 0 }));
            return;
        }
        // > store (standalone, may include MW[...])
        m = trimmed.match(ST_RE);
        if (m) {
            const rest = m[2].trim();
            if (rest.toUpperCase().startsWith('MW[')) {
                this._emitStoreSuffix(`${m[1] || ''} ${rest}`.trim());
            } else {
                this._emitStoreLine(m[1], m[2]);
            }
            return;
        }
        throw new Error(`Unknown PROG line: ${line}`);
    }

    _emitAtChain(line) {
        const m = line.match(AT_RE);
        if (!m) throw new Error(`Bad '@' line: ${line}`);
        const prods = expandProducts(m[1], this.syms);

        // First product: ZERO=1 (no augend)
        const [pmf0, yf0] = prods[0];
        this.progWords.push(packMpro({
            SHFT: 0, ZERO: 1, BSEL: 0, NEGB: 0,
            TRA: pmf0.TRA || 0, XSEL: pmf0.XSEL || 0, IRA: pmf0.IRA || 0,
            YSEL: yf0.YSEL || 0, CRA: yf0.CRA || 0,
        }));
        // Subsequent: accumulate with BSEL=1 (REG/ACC)
        for (let i = 1; i < prods.length; i++) {
            const [pmf, yf] = prods[i];
            this.progWords.push(packMpro({
                SHFT: 0, ZERO: 0, BSEL: 1, NEGB: 0,
                TRA: pmf.TRA || 0, XSEL: pmf.XSEL || 0, IRA: pmf.IRA || 0,
                YSEL: yf.YSEL || 0, CRA: yf.CRA || 0,
            }));
        }
    }

    _emitStoreSuffix(text) {
        const m = text.match(/^([Ss][123])?\s*(.*)$/);
        if (!m) throw new Error(`Bad store suffix '> ${text}'`);
        const opt = m[1];
        const rest = m[2].trim();
        if (rest.toUpperCase().startsWith('MW[') && rest.endsWith(']')) {
            const inner = rest.slice(3, -1);
            const a = parseAddrExpr(inner, this.syms);
            this.progWords.push(packMpro({
                MWT: 1, SHFT: 0, BSEL: 1, YSEL: 1, CRA: 0,
                MASA: a.masa & 0x1F, TABLE: a.TABLE,
                ADREB: a.ADREB, NXADR: a.NXADR, NOFL: a.NOFL,
            }));
            return;
        }
        this._emitStoreLine(opt, rest);
    }

    _emitStoreLine(opt, destsStr) {
        const dests = destsStr.split(',').map(d => d.trim().toUpperCase());
        const [SHFT] = shftForStore(opt || null);
        let TWT = 0, TWA = 0, EWT = 0, EWA = 0, FRCL = 0, ADRL = 0;
        for (const d of dests) {
            if (d.startsWith('TEMP'))       { TWT = 1; TWA = parseInt(d.slice(4), 10); }
            else if (d.startsWith('EFREG')) { EWT = 1; EWA = parseInt(d.slice(5), 10); }
            else if (d === 'FREG')          { FRCL = 1; }
            else if (d === 'ADREG')         { ADRL = 1; }
            else if (d === '')              { continue; }
            else throw new Error(`Bad store dest '${d}' (use TEMPxx, EFREGxx, FREG, ADREG)`);
        }
        this.progWords.push(packMpro({
            SHFT, TWT, TWA, EWT, EWA, FRCL, ADRL, BSEL: 1, YSEL: 1, CRA: 0,
        }));
    }

    /**
     * Insert NOPs so that every memory-accessing instruction (MRD/MWT)
     * lands on an odd-numbered DSP step.  Returns the number of NOPs
     * inserted and an array of warning strings.
     */
    alignMemoryOps() {
        const aligned = [];
        const warnings = [];
        for (let i = 0; i < this.progWords.length; i++) {
            const w = this.progWords[i];
            if (instrAccessesMem(w) && (aligned.length & 1) === 0) {
                // Would land on an even step — insert a NOP first
                warnings.push(
                    `Inserted NOP at step ${aligned.length} to align memory ` +
                    `access (originally instruction ${i + 1}) to odd step ${aligned.length + 1}`
                );
                aligned.push(NOP_PACKED);
            }
            aligned.push(w);
        }
        if (aligned.length > 128) {
            warnings.push(
                `Program is ${aligned.length} steps after alignment ` +
                `(max 128) — truncated`
            );
        }
        this.progWords = aligned;
        return warnings;
    }

    /** Build typed arrays ready for scsp_dsp_load_arrays(). */
    getArrays(rbl) {
        // COEF: shift left by 3 (SCSP reads bits [15:3] as 13-bit signed)
        const coef = new Int16Array(64);
        for (let i = 0; i < this.syms.coefOrder.length && i < 64; i++) {
            const name = this.syms.coefOrder[i];
            const raw = this.syms.coef[name] || 0;
            coef[i] = (i === 0) ? 0 : ((raw << 3) & 0xFFFF) << 16 >> 16;  // sign-extend
        }
        // MADRS
        const madrs = new Uint16Array(32);
        for (let i = 0; i < this.syms.adrsOrder.length && i < 32; i++) {
            madrs[i] = this.syms.adrs[this.syms.adrsOrder[i]] || 0;
        }
        // MPRO: 128 steps × 4 words, pad with zeros
        const mpro = new Uint16Array(512);
        for (let i = 0; i < this.progWords.length && i < 128; i++) {
            const [w3, w2, w1, w0] = this.progWords[i];
            mpro[i * 4 + 0] = w3;
            mpro[i * 4 + 1] = w2;
            mpro[i * 4 + 2] = w1;
            mpro[i * 4 + 3] = w0;
        }
        return {
            mpro, coef, madrs,
            rbl: (rbl != null) ? rbl : 0,
            steps: this.progWords.length,
        };
    }

    /** Build a 1344-byte EXB binary (Uint8Array) for export. */
    getExb(name, rbl) {
        const exb = new Uint8Array(1344);
        // Name at 0x00 (32 bytes ASCII)
        const nameBytes = new TextEncoder().encode((name || 'effect.EXB').slice(0, 31));
        exb.set(nameBytes, 0);
        // RBL at 0x20
        exb[0x20] = (rbl || 0) & 3;
        // COEF at 0x40 (64 × 16-bit BE)
        const arrays = this.getArrays(rbl);
        for (let i = 0; i < 64; i++) {
            const v = arrays.coef[i] & 0xFFFF;
            exb[0x40 + i * 2] = (v >> 8) & 0xFF;
            exb[0x40 + i * 2 + 1] = v & 0xFF;
        }
        // MADRS at 0xC0 (64 × 16-bit BE, first 32 from assembler, rest zero)
        for (let i = 0; i < 32; i++) {
            const v = arrays.madrs[i];
            exb[0xC0 + i * 2] = (v >> 8) & 0xFF;
            exb[0xC0 + i * 2 + 1] = v & 0xFF;
        }
        // MPRO at 0x140 (128 × 8 bytes)
        for (let i = 0; i < 512; i++) {
            const v = arrays.mpro[i];
            exb[0x140 + i * 2] = (v >> 8) & 0xFF;
            exb[0x140 + i * 2 + 1] = v & 0xFF;
        }
        return exb;
    }
}

// ─── Public API ─────────────────────────────────────────────────────

/**
 * Assemble USC text into SCSP DSP arrays.
 * @param {string} text — USC assembly source
 * @param {object} [opts] — { rbl: 0-3 }
 * @returns {{ mpro: Uint16Array, coef: Int16Array, madrs: Uint16Array,
 *             rbl: number, steps: number, errors: string[] }}
 */
function scspdspAssemble(text, opts) {
    const errors = [];
    const warnings = [];
    const asm = new Assembler();
    try {
        asm.assemble(text);
    } catch (e) {
        errors.push(e.message);
    }
    // Auto-align memory ops to odd steps (insert NOPs as needed)
    if (!errors.length) {
        warnings.push(...asm.alignMemoryOps());
    }
    const rbl = (opts && opts.rbl != null) ? opts.rbl : 0;
    const result = asm.getArrays(rbl);
    result.errors = errors;
    result.warnings = warnings;
    return result;
}

/**
 * Assemble USC text and return an EXB binary.
 * @param {string} text — USC assembly source
 * @param {object} [opts] — { rbl: 0-3, name: string }
 * @returns {{ exb: Uint8Array, steps: number, errors: string[] }}
 */
function scspdspAssembleExb(text, opts) {
    const errors = [];
    const warnings = [];
    const asm = new Assembler();
    try {
        asm.assemble(text);
    } catch (e) {
        errors.push(e.message);
    }
    if (!errors.length) {
        warnings.push(...asm.alignMemoryOps());
    }
    const rbl = (opts && opts.rbl != null) ? opts.rbl : 0;
    const name = (opts && opts.name) || 'effect.EXB';
    return {
        exb: asm.getExb(name, rbl),
        steps: asm.progWords.length,
        errors,
        warnings,
    };
}

/**
 * Parse an EXB binary (Uint8Array) into arrays suitable for
 * scsp_dsp_load_arrays().  For loading pre-built .EXB files.
 */
function scspdspParseExb(exb) {
    if (exb.length < 0x540) throw new Error('EXB too small (need 1344 bytes)');
    const rbl = exb[0x20] & 3;
    const coef = new Int16Array(64);
    for (let i = 0; i < 64; i++)
        coef[i] = ((exb[0x40 + i * 2] << 8) | exb[0x40 + i * 2 + 1]) << 16 >> 16;
    const madrs = new Uint16Array(32);
    for (let i = 0; i < 32; i++)
        madrs[i] = (exb[0xC0 + i * 2] << 8) | exb[0xC0 + i * 2 + 1];
    const mpro = new Uint16Array(512);
    for (let i = 0; i < 512; i++)
        mpro[i] = (exb[0x140 + i * 2] << 8) | exb[0x140 + i * 2 + 1];
    const name = new TextDecoder().decode(exb.slice(0, 32)).replace(/\0/g, '').trim();
    let steps = 0;
    for (let i = 127; i >= 0; i--) {
        if (mpro[i * 4] || mpro[i * 4 + 1] || mpro[i * 4 + 2] || mpro[i * 4 + 3]) {
            steps = i + 1; break;
        }
    }
    return { mpro, coef, madrs, rbl, name, steps };
}

// ─── Export (works in Node.js and browser) ──────────────────────────

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { scspdspAssemble, scspdspAssembleExb, scspdspParseExb, Assembler, packMpro };
}
