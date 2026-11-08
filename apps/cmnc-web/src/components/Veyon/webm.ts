// Finalize MediaRecorder's live WebM: duration and an index of video keyframes.
// Payloads remain Blob slices, so long recordings are not copied into a byte array.
const SEGMENT = 0x18538067, INFO = 0x1549a966, CLUSTER = 0x1f43b675;
function bytes(value: number, length = 8) {
    const data = new Uint8Array(length);
    for (let i = length - 1; i >= 0; i--) { data[i] = value % 256; value = Math.floor(value / 256); }
    return data;
}
function element(id: number, parts: BlobPart[]) {
    const payload = new Blob(parts);
    const size = bytes(payload.size, 8); size[0] |= 1;
    return new Blob([bytes(id, Math.ceil(Math.log2(id + 1) / 8)), size, payload]);
}
export async function finalizeWebm(file: Blob, seconds: number): Promise<Blob> {
    let cache = new Uint8Array(), cacheAt = -1;
    async function header(at: number) {
        if (at < cacheAt || at + 16 > cacheAt + cache.length) { cacheAt = at; cache = new Uint8Array(await file.slice(at, at + 65536).arrayBuffer()); }
        let cursor = at - cacheAt;
        function vint(id = false) {
            const first = cache[cursor++];
            if (!first) throw new Error("РџРѕРІСЂРµР¶РґС‘РЅ Р·Р°РіРѕР»РѕРІРѕРє WebM");
            let length = 1, mask = 128;
            while (!(first & mask)) { length++; mask >>= 1; }
            let value = id ? first : first & (mask - 1);
            let unknown = !id && value === mask - 1;
            for (let i = 1; i < length; i++) { const byte = cache[cursor++]; value = value * 256 + byte; unknown = unknown && byte === 255; }
            return unknown ? Infinity : value;
        }
        const id = vint(true), size = vint();
        const data = cacheAt + cursor;
        return { id, at, data, end: Math.min(file.size, data + size), unknown: !Number.isFinite(size) };
    }
    async function uint(start: number, end: number) { let value = 0; for (const byte of new Uint8Array(await file.slice(start, end).arrayBuffer())) value = value * 256 + byte; return value; }
    let segment = await header(0);
    while (segment.id !== SEGMENT && segment.end < file.size) segment = await header(segment.end);
    if (segment.id !== SEGMENT) throw new Error("РќРµ РЅР°Р№РґРµРЅ СЃРµРіРјРµРЅС‚ WebM");
    const children: { blob: Blob; cues: { time: number; relative: number; track: number }[]; id: number }[] = [];
    let scale = 1_000_000;
    for (let at = segment.data; at < segment.end;) {
        const item = await header(at);
        if (item.id === INFO) {
            const fields: BlobPart[] = [];
            for (let pos = item.data; pos < item.end;) {
                const field = await header(pos);
                if (field.id === 0x2ad7b1) scale = await uint(field.data, field.end);
                if (field.id !== 0x4489) fields.push(file.slice(pos, field.end));
                pos = field.end;
            }
            const duration = new ArrayBuffer(8); new DataView(duration).setFloat64(0, seconds * 1e9 / scale);
            children.push({ id: INFO, blob: element(INFO, [...fields, element(0x4489, [duration])]), cues: [] });
        } else if (item.id === CLUSTER) {
            let time = 0, end = item.end;
            const cues: { time: number; relative: number; track: number }[] = [];
            for (let pos = item.data; pos < item.end;) {
                const block = await header(pos);
                if (block.id === CLUSTER || block.id === 0x1c53bb6b) { end = pos; break; }
                if (block.id === 0xe7) time = await uint(block.data, block.end);
                if (block.id === 0xa3) {
                    const data = new Uint8Array(await file.slice(block.data, block.data + 12).arrayBuffer());
                    let length = 1, mask = 128; while (!(data[0] & mask)) { length++; mask >>= 1; }
                    let track = data[0] & (mask - 1); for (let i = 1; i < length; i++) track = track * 256 + data[i];
                    const offset = new DataView(data.buffer).getInt16(length);
                    if (data[length + 2] & 128) cues.push({ time: Math.max(0, time + offset), relative: pos - item.data, track });
                }
                if (block.end <= pos) throw new Error("РџРѕРІСЂРµР¶РґС‘РЅ Р±Р»РѕРє WebM");
                pos = block.end;
            }
            children.push({ id: CLUSTER, blob: file.slice(at, end), cues });
            at = end; continue;
        } else if (item.id !== 0x114d9b74 && item.id !== 0x1c53bb6b) children.push({ id: item.id, blob: file.slice(at, item.end), cues: [] });
        if (item.end <= at) throw new Error("РџРѕРІСЂРµР¶РґС‘РЅ СЃРµРіРјРµРЅС‚ WebM");
        at = item.end;
    }
    const seek = (position: number) => element(0x114d9b74, [element(0x4dbb, [element(0x53ab, [bytes(0x1c53bb6b, 4)]), element(0x53ac, [bytes(position)])])]);
    let position = seek(0).size;
    const points: BlobPart[] = [];
    for (const child of children) {
        for (const cue of child.cues) points.push(element(0xbb, [element(0xb3, [bytes(cue.time)]), element(0xb7, [element(0xf7, [bytes(cue.track)]), element(0xf1, [bytes(position)]), element(0xf0, [bytes(cue.relative)])])]));
        position += child.blob.size;
    }
    return new Blob([file.slice(0, segment.at), bytes(SEGMENT, 4), new Uint8Array([1,255,255,255,255,255,255,255]), seek(position), ...children.map(child => child.blob), element(0x1c53bb6b, points)], { type: "video/webm" });
}
