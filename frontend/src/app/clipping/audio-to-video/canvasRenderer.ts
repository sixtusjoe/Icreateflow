// ─── WebGL2 Renderer ─────────────────────────────────────────────────────────
// GPU-first renderer using WebGL2 + GLSL shaders for all visual effects.
// Text (karaoke + NOW PLAYING) is rendered to an offscreen Canvas 2D and
// composited as a WebGL texture — the only Canvas 2D usage in the pipeline.
// Maintains the same CanvasRenderer interface as the previous Canvas 2D build.
// ─────────────────────────────────────────────────────────────────────────────

/* ── Types ────────────────────────────────────────────────────────────────── */

export interface AudioWord {
  id?: number;
  word: string;
  start_s: number;
  end_s: number;
}

export interface ThemeColors {
  accent: string;
  textGlow: string;
}

export type ThemeId = "minimal" | "vivid" | "neon" | "inferno";

export interface RendererConfig {
  width: number;
  height: number;
  themeId: ThemeId;
  theme: ThemeColors;
  words: AudioWord[];
  bgImageUrl: string | null;
  coverImageUrl: string | null;
  clipStartS: number;
  clipDuration: number;
  renderMode?: "match" | "upgraded"; // "match" = exact HTML fidelity, "upgraded" = bloom + softer particles
}

export interface CanvasRenderer {
  canvas: HTMLCanvasElement;
  renderFrame(audioCurrentTime: number): void;
  destroy(): void;
}

/* ── GLSL Shaders ─────────────────────────────────────────────────────────── */

// Universal screen-space vertex shader — all quads use this
const VS_SCREEN = `#version 300 es
precision highp float;
in vec2 a_pos;
uniform vec2 u_res;
out vec2 v_uv;
out vec2 v_pos;
void main(){
  v_pos = a_pos;
  v_uv = a_pos / u_res;
  gl_Position = vec4(
    a_pos.x / u_res.x * 2.0 - 1.0,
    1.0 - a_pos.y / u_res.y * 2.0,
    0.0, 1.0
  );
}`;

// Simple texture blit (flips Y so Canvas-2D textures appear right-side-up)
const FS_BLIT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_alpha;
out vec4 outColor;
void main(){
  vec4 c = texture(u_tex, vec2(v_uv.x, 1.0 - v_uv.y));
  outColor = vec4(c.rgb, c.a * u_alpha);
}`;

// Gradient overlay (matches the two-layer HTML gradient)
const FS_GRADIENT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform vec3 u_dark;
out vec4 outColor;
void main(){
  float y = v_uv.y;
  float a1;
  if(y < 0.44) a1 = mix(0.88, 0.20, y / 0.44);
  else if(y < 0.56) a1 = 0.20;
  else a1 = mix(0.20, 0.90, (y - 0.56) / 0.44);
  float a2;
  if(y < 0.4)       a2 = mix(0.60, 0.0, y / 0.4);
  else if(y < 0.6)  a2 = 0.0;
  else              a2 = mix(0.0, 0.80, (y - 0.6) / 0.4);
  vec3 col = u_dark / 255.0 * a1 + vec3(0.0) * a2;
  outColor = vec4(u_dark / 255.0, a1 + a2 * (1.0 - a1));
}`;

// Radial gradient — for blobs, center glow, template tints
const FS_RADIAL = `#version 300 es
precision highp float;
in vec2 v_pos;
uniform vec2 u_center;
uniform float u_radius;
uniform vec4 u_color;
out vec4 outColor;
void main(){
  float d = length(v_pos - u_center) / u_radius;
  float a = max(0.0, 1.0 - d);
  outColor = vec4(u_color.rgb, u_color.a * a);
}`;

// Ring / disc SDF — dashed ring, solid ring, full disc
const FS_RING = `#version 300 es
precision highp float;
in vec2 v_pos;
uniform vec2  u_center;
uniform float u_r_inner;
uniform float u_r_outer;
uniform vec4  u_color;
uniform float u_dash_count; // 0 = solid
uniform float u_rot;
out vec4 outColor;
void main(){
  vec2 d = v_pos - u_center;
  float dist = length(d);
  float aa = 1.5;
  if(dist < u_r_inner - aa || dist > u_r_outer + aa) discard;
  if(u_dash_count > 0.0){
    float angle = atan(d.y, d.x) - u_rot;
    float norm  = mod(angle, 6.28318) / 6.28318;
    float period = 1.0 / u_dash_count;
    float phase  = mod(norm, period) / period;
    if(phase > 0.55) discard;
  }
  float innerA = smoothstep(u_r_inner - aa, u_r_inner + aa, dist);
  float outerA = smoothstep(u_r_outer + aa, u_r_outer - aa, dist);
  outColor = vec4(u_color.rgb, u_color.a * innerA * outerA);
}`;

// Rounded-rect fill — frosted glass (samples pre-blurred bg texture)
const FS_CARD_FILL = `#version 300 es
precision highp float;
in vec2 v_pos;
in vec2 v_uv;
uniform sampler2D u_blur;
uniform vec2  u_card_pos;
uniform vec2  u_card_size;
uniform float u_card_r;
uniform vec4  u_tint;
out vec4 outColor;
float sdRR(vec2 p, vec2 b, float r){
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main(){
  vec2 center = u_card_pos + u_card_size * 0.5;
  float d = sdRR(v_pos - center, u_card_size * 0.5, u_card_r);
  if(d > 0.5) discard;
  float aa = smoothstep(0.5, -0.5, d);
  vec4 blurred = texture(u_blur, vec2(v_uv.x, 1.0 - v_uv.y));
  vec3 col = blurred.rgb * (1.0 - u_tint.a) + u_tint.rgb * u_tint.a;
  outColor = vec4(col, aa);
}`;

// Rounded-rect border
const FS_CARD_BORDER = `#version 300 es
precision highp float;
in vec2 v_pos;
uniform vec2  u_card_pos;
uniform vec2  u_card_size;
uniform float u_card_r;
uniform vec4  u_border_color;
uniform float u_border_w;
uniform vec4  u_glow_color;
uniform float u_glow_r;
out vec4 outColor;
float sdRR(vec2 p, vec2 b, float r){
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main(){
  vec2 center = u_card_pos + u_card_size * 0.5;
  float d = sdRR(v_pos - center, u_card_size * 0.5, u_card_r);
  float aa = 1.5;
  float borderA = smoothstep(u_border_w + aa, u_border_w - aa, abs(d)) *
                  smoothstep(-aa, aa, d) * u_border_color.a;
  float glowA = 0.0;
  if(u_glow_r > 0.0){
    glowA = smoothstep(u_glow_r, 0.0, d) * u_glow_color.a * 0.35;
  }
  float totalA = max(borderA, glowA);
  if(totalA < 0.01) discard;
  vec3 col = mix(u_glow_color.rgb, u_border_color.rgb, borderA / max(totalA, 0.001));
  outColor = vec4(col, totalA);
}`;

// Circle-clipped texture (album cover inside a circle)
const FS_COVER_CIRCLE = `#version 300 es
precision highp float;
in vec2 v_pos;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2  u_center;
uniform float u_radius;
uniform float u_scale; // for pulsing
uniform vec4  u_tint;  // overlay tint
out vec4 outColor;
void main(){
  float dist = length(v_pos - u_center);
  float r    = u_radius * u_scale;
  float aa   = 1.5;
  if(dist > r + aa) discard;
  float alpha = smoothstep(r + aa, r - aa, dist);
  // Map pos to cover texture UV
  vec2 uv = (v_pos - u_center + r) / (r * 2.0);
  uv.y = 1.0 - uv.y;
  vec4 col = texture(u_tex, uv);
  outColor = vec4(col.rgb * (1.0-u_tint.a) + u_tint.rgb * u_tint.a, alpha);
}`;

// Rounded-rect clipped texture (vivid album cover)
const FS_COVER_RRECT = `#version 300 es
precision highp float;
in vec2 v_pos;
uniform sampler2D u_tex;
uniform vec2  u_pos;
uniform vec2  u_size;
uniform float u_corner;
uniform vec4  u_tint;
out vec4 outColor;
float sdRR(vec2 p, vec2 b, float r){
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main(){
  vec2 center = u_pos + u_size * 0.5;
  float d = sdRR(v_pos - center, u_size * 0.5, u_corner);
  float aa = 1.5;
  if(d > aa) discard;
  float alpha = smoothstep(aa, -aa, d);
  vec2 uv = (v_pos - u_pos) / u_size;
  uv.y = 1.0 - uv.y;
  uv = clamp(uv, 0.0, 1.0);
  vec4 col = texture(u_tex, uv);
  outColor = vec4(col.rgb + u_tint.rgb * u_tint.a, alpha);
}`;

// Neon vinyl — disc + conic sweep + groove rings (all in one shader)
const FS_VINYL = `#version 300 es
precision highp float;
in vec2 v_pos;
uniform vec2  u_center;
uniform float u_disc_r;
uniform float u_spin;       // radians, current rotation
uniform float u_cover_r;    // center cover circle radius
uniform vec3  u_accent;     // cyan
out vec4 outColor;
void main(){
  vec2 d   = v_pos - u_center;
  float r  = length(d);
  float aa = 1.5;
  if(r > u_disc_r + aa) discard;
  if(r > u_disc_r - aa){
    float edge = smoothstep(u_disc_r + aa, u_disc_r - aa, r);
    outColor = vec4(u_accent, 0.5 * edge);
    return;
  }
  // Inside disc
  float angle = atan(d.y, d.x) - u_spin;
  // Conic sweep: 20-degree fading arc
  float norm = mod(angle, 6.28318) / 6.28318;
  float sweepAlpha = 0.0;
  if(norm < 0.056) sweepAlpha = (1.0 - norm / 0.056) * 0.4; // leading edge

  // Groove rings at insets
  float groove = 0.0;
  float insets[4]; insets[0]=0.05; insets[1]=0.15; insets[2]=0.25; insets[3]=0.35;
  for(int i=0; i<4; i++){
    float gr = u_disc_r * (1.0 - insets[i]);
    groove += smoothstep(gr+1.5, gr-1.5, r) * smoothstep(gr-3.5, gr-1.5, r) * 0.10;
  }

  // Centre hole (cover area — just black, texture drawn separately)
  if(r < u_cover_r) {
    outColor = vec4(0.0, 0.0, 0.0, 1.0);
    return;
  }

  vec3 col = vec3(0.039, 0.039, 0.039); // dark disc #0A0A0A
  col += u_accent * sweepAlpha;
  col += vec3(1.0) * groove;
  outColor = vec4(col, 1.0);
}`;

// Particle point sprites
const VS_PARTICLE = `#version 300 es
precision highp float;
in float a_x;
in float a_size;
in float a_speed;
in float a_delay;
in float a_period;
in float a_xdrift;
uniform float u_time;
uniform vec2  u_res;
uniform float u_upgraded; // 0=match, 1=upgraded (larger splat)
out float v_alpha;
void main(){
  float elapsed = mod(u_time - a_delay, a_period);
  if(elapsed < 0.0) elapsed += a_period;
  float progress = elapsed / a_period;
  float px = a_x * u_res.x + a_xdrift * elapsed;
  float py = u_res.y - a_speed * elapsed;
  float alpha;
  if(progress < 0.3) alpha = (progress / 0.3) * 0.8;
  else alpha = 0.8 * (1.0 - (progress - 0.3) / 0.7);
  v_alpha = max(0.0, alpha);
  gl_Position = vec4(px / u_res.x * 2.0 - 1.0, 1.0 - py / u_res.y * 2.0, 0.0, 1.0);
  gl_PointSize = a_size * (1.0 + u_upgraded * 1.5);
}`;

const FS_PARTICLE = `#version 300 es
precision highp float;
in float v_alpha;
uniform vec3  u_color;
uniform float u_upgraded;
out vec4 outColor;
void main(){
  vec2 pc = gl_PointCoord - 0.5;
  float d = length(pc) * 2.0;
  float shape;
  if(u_upgraded > 0.5){
    shape = exp(-d * d * 2.5); // soft gaussian splat
  } else {
    shape = step(d, 1.0);      // hard circle
  }
  if(shape < 0.01) discard;
  outColor = vec4(u_color, v_alpha * shape);
}`;

// Flame sprites (elliptical, white, screen blend)
const VS_FLAME = `#version 300 es
precision highp float;
in float a_x;
in float a_w;
in float a_h;
in float a_speed;
in float a_delay;
in float a_period;
uniform float u_time;
uniform vec2  u_res;
out float v_alpha;
out vec2  v_size;
void main(){
  float elapsed = mod(u_time - a_delay, a_period);
  if(elapsed < 0.0) elapsed += a_period;
  float progress = elapsed / a_period;
  float px = a_x * u_res.x;
  float py = u_res.y * 1.1 - a_speed * elapsed;
  float scaleY = 1.0 + 1.5 * progress;
  float scaleX = 1.0 - 0.5 * progress;
  float alpha;
  if(progress < 0.4) alpha = (progress / 0.4) * 0.6;
  else alpha = 0.6 * (1.0 - (progress - 0.4) / 0.6);
  v_alpha = max(0.0, alpha) * 0.70;
  v_size  = vec2(a_w * scaleX, a_h * scaleY);
  gl_Position = vec4(px / u_res.x * 2.0 - 1.0, 1.0 - py / u_res.y * 2.0, 0.0, 1.0);
  gl_PointSize = max(v_size.x, v_size.y) * 0.8;
}`;

const FS_FLAME = `#version 300 es
precision highp float;
in float v_alpha;
in vec2  v_size;
out vec4 outColor;
void main(){
  vec2 pc = gl_PointCoord - 0.5;
  float d = length(pc) * 2.0;
  float shape = exp(-d * d * 1.5);
  if(shape < 0.02) discard;
  outColor = vec4(1.0, 1.0, 1.0, v_alpha * shape);
}`;

// Zigzag waveform — rendered as a triangle strip
const VS_ZIGZAG = `#version 300 es
precision highp float;
in vec2 a_pos;
uniform vec2 u_res;
out float v_x_norm; // 0..1 along the waveform
void main(){
  v_x_norm = a_pos.x / u_res.x; // approximate — refined per vertex
  gl_Position = vec4(a_pos.x / u_res.x * 2.0 - 1.0, 1.0 - a_pos.y / u_res.y * 2.0, 0.0, 1.0);
}`;

const FS_ZIGZAG = `#version 300 es
precision highp float;
in float v_x_norm;
uniform vec3  u_color;
uniform float u_alpha;
out vec4 outColor;
void main(){
  outColor = vec4(u_color, u_alpha);
}`;

// Separable Gaussian blur (used for background and bloom)
const FS_BLUR = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2  u_step;   // (1/w, 0) or (0, 1/h) times sigma direction
uniform float u_sigma;
out vec4 outColor;
float gw(float x){ return exp(-0.5 * x * x / (u_sigma * u_sigma)); }
void main(){
  vec2 uv = vec2(v_uv.x, 1.0 - v_uv.y);
  vec4 sum = vec4(0.0);
  float norm = 0.0;
  int R = int(u_sigma * 2.5);
  R = min(R, 48);
  for(int i = -48; i <= 48; i++){
    if(abs(i) > R) continue;
    float w = gw(float(i));
    sum  += texture(u_tex, uv + u_step * float(i)) * w;
    norm += w;
  }
  outColor = sum / norm;
}`;

// Bloom: extract bright pixels
const FS_BLOOM_BRIGHT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_threshold;
out vec4 outColor;
void main(){
  vec4 c = texture(u_tex, vec2(v_uv.x, 1.0 - v_uv.y));
  float lum = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
  float br  = max(0.0, lum - u_threshold) / (1.0 - u_threshold + 0.001);
  outColor  = vec4(c.rgb * br * 1.5, 1.0);
}`;

// Bloom: additive composite
const FS_BLOOM_COMP = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_scene;
uniform sampler2D u_bloom;
uniform float u_strength;
out vec4 outColor;
void main(){
  vec2 uv = vec2(v_uv.x, 1.0 - v_uv.y);
  vec4 scene = texture(u_scene, uv);
  vec4 bloom = texture(u_bloom, uv);
  outColor = vec4(scene.rgb + bloom.rgb * u_strength, scene.a);
}`;

/* ── WebGL Helpers ────────────────────────────────────────────────────────── */

function mkShader(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
    throw new Error("Shader compile error:\n" + gl.getShaderInfoLog(s) + "\n---\n" + src);
  return s;
}

function mkProg(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram {
  const p = gl.createProgram()!;
  gl.attachShader(p, mkShader(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, mkShader(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS))
    throw new Error("Program link error: " + gl.getProgramInfoLog(p));
  return p;
}

interface FBOBundle { fbo: WebGLFramebuffer; tex: WebGLTexture; }
function mkFBO(gl: WebGL2RenderingContext, w: number, h: number): FBOBundle {
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const fbo = gl.createFramebuffer()!;
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  return { fbo, tex };
}

function mkTex(gl: WebGL2RenderingContext): WebGLTexture {
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return tex;
}

function uploadImageToTex(gl: WebGL2RenderingContext, tex: WebGLTexture, src: HTMLImageElement | HTMLCanvasElement) {
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);  // Canvas 2D / images have Y=0 at top; GL textures need Y=0 at bottom
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
}

// Make a static position buffer for a screen-space quad (two triangles)
function mkQuadBuf(gl: WebGL2RenderingContext, x1: number, y1: number, x2: number, y2: number): WebGLBuffer {
  const buf = gl.createBuffer()!;
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    x1, y1,  x2, y1,  x1, y2,
    x2, y1,  x2, y2,  x1, y2,
  ]), gl.STATIC_DRAW);
  return buf;
}

// Draw a quad using the screen-space VS (a_pos attribute)
function drawQuad(gl: WebGL2RenderingContext, prog: WebGLProgram, buf: WebGLBuffer) {
  const loc = gl.getAttribLocation(prog, "a_pos");
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
  gl.disableVertexAttribArray(loc);
}

function uni1f(gl: WebGL2RenderingContext, p: WebGLProgram, n: string, v: number) {
  gl.uniform1f(gl.getUniformLocation(p, n), v);
}
function uni2f(gl: WebGL2RenderingContext, p: WebGLProgram, n: string, x: number, y: number) {
  gl.uniform2f(gl.getUniformLocation(p, n), x, y);
}
function uni3f(gl: WebGL2RenderingContext, p: WebGLProgram, n: string, x: number, y: number, z: number) {
  gl.uniform3f(gl.getUniformLocation(p, n), x, y, z);
}
function uni4f(gl: WebGL2RenderingContext, p: WebGLProgram, n: string, x: number, y: number, z: number, w: number) {
  gl.uniform4f(gl.getUniformLocation(p, n), x, y, z, w);
}
function uniTex(gl: WebGL2RenderingContext, p: WebGLProgram, n: string, tex: WebGLTexture, unit: number) {
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.uniform1i(gl.getUniformLocation(p, n), unit);
}

/* ── Image / Seed helpers ─────────────────────────────────────────────────── */

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise(resolve => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload  = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function hexToRgb01(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0,2),16)/255, parseInt(h.slice(2,4),16)/255, parseInt(h.slice(4,6),16)/255];
}

interface PSeed { x:number; size:number; speed:number; delay:number; period:number; xDrift:number; }
interface FSeed { x:number; w:number; h:number; speed:number; delay:number; period:number; }

function makeParticleSeeds(n: number): PSeed[] {
  return Array.from({length:n}, () => ({
    x: Math.random(),
    size: Math.random()*4+1,
    speed: (800+Math.random()*400)/(Math.random()*4+4),
    delay: Math.random()*4,
    period: Math.random()*4+4,
    xDrift: (Math.random()-0.5)*100/(Math.random()*4+4),
  }));
}

function makeFlameSeeds(n: number): FSeed[] {
  return Array.from({length:n}, () => ({
    x: Math.random()*0.8+0.1,
    w: Math.random()*60+40,
    h: Math.random()*100+80,
    speed: (400+Math.random()*300)/(Math.random()*2+1.5),
    delay: Math.random()*2,
    period: Math.random()*2+1.5,
  }));
}

/* ── Two-pass blur helper ─────────────────────────────────────────────────── */

function runBlurPass(
  gl: WebGL2RenderingContext,
  blurProg: WebGLProgram,
  fullQuad: WebGLBuffer,
  srcTex: WebGLTexture,
  dstFBO: FBOBundle,
  stepX: number, stepY: number, sigma: number,
  CW: number, CH: number,
) {
  gl.bindFramebuffer(gl.FRAMEBUFFER, dstFBO.fbo);
  gl.viewport(0, 0, CW, CH);
  gl.useProgram(blurProg);
  uni2f(gl, blurProg, "u_res", CW, CH);
  uniTex(gl, blurProg, "u_tex", srcTex, 0);
  uni2f(gl, blurProg, "u_step", stepX, stepY);
  uni1f(gl, blurProg, "u_sigma", sigma);
  drawQuad(gl, blurProg, fullQuad);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}

/* ── Factory ──────────────────────────────────────────────────────────────── */

export async function createCanvasRenderer(cfg: RendererConfig): Promise<CanvasRenderer> {
  const { width: CW, height: CH, themeId: tid, theme, words } = cfg;
  const upgraded = cfg.renderMode === "upgraded";
  const [acR, acG, acB] = hexToRgb01(theme.accent);

  const THEME_DARK: Record<string, [number,number,number]> = {
    minimal: [8,10,14], vivid: [18,0,26], neon: [0,0,0], inferno: [10,8,8],
  };
  const dark = THEME_DARK[tid] ?? [8,10,14];

  // Layout (mirrors CSS %)
  const CARD_X = Math.round(CW * 0.08);
  const CARD_Y = Math.round(CH * 0.06);
  const CARD_W = CW - 2 * CARD_X;
  const CARD_H = Math.round(CH * 0.46);
  const CARD_R = 60;
  const ART_PAD = 48;
  const ART_X  = CARD_X + ART_PAD;
  const ART_Y  = CARD_Y + ART_PAD;
  const ART_W  = CARD_W - 2 * ART_PAD;
  const ART_H  = CARD_H - 2 * ART_PAD - 80;
  const ART_CX = ART_X + ART_W / 2;
  const ART_CY = ART_Y + ART_H / 2;
  const ART_R  = Math.min(ART_W, ART_H) / 2;
  const ZIG_X  = Math.round(CW * 0.13);
  const ZIG_Y  = Math.round(CH * 0.588);
  const ZIG_W  = Math.round(CW * 0.74);
  const ZIG_H  = 30;
  const LYRIC_Y = Math.round(CH * 0.80);
  const GROUP_SZ = 5;

  // ── WebGL2 context ────────────────────────────────────────────────────────
  const canvas = document.createElement("canvas");
  canvas.width = CW;
  canvas.height = CH;
  const gl = canvas.getContext("webgl2", { alpha: false, antialias: false, preserveDrawingBuffer: true })!;
  if (!gl) throw new Error("WebGL2 not supported");

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.viewport(0, 0, CW, CH);

  // ── Compile shader programs ───────────────────────────────────────────────
  const blitProg    = mkProg(gl, VS_SCREEN, FS_BLIT);
  const gradProg    = mkProg(gl, VS_SCREEN, FS_GRADIENT);
  const radialProg  = mkProg(gl, VS_SCREEN, FS_RADIAL);
  const ringProg    = mkProg(gl, VS_SCREEN, FS_RING);
  const cardFillProg= mkProg(gl, VS_SCREEN, FS_CARD_FILL);
  const cardBordProg= mkProg(gl, VS_SCREEN, FS_CARD_BORDER);
  const coverCirProg= mkProg(gl, VS_SCREEN, FS_COVER_CIRCLE);
  const coverRRProg = mkProg(gl, VS_SCREEN, FS_COVER_RRECT);
  const vinylProg   = mkProg(gl, VS_SCREEN, FS_VINYL);
  const partProg    = mkProg(gl, VS_PARTICLE, FS_PARTICLE);
  const flameProg   = mkProg(gl, VS_FLAME, FS_FLAME);
  const zigProg     = mkProg(gl, VS_ZIGZAG, FS_ZIGZAG);
  const blurProg    = mkProg(gl, VS_SCREEN, FS_BLUR);
  const bloomBrProg = mkProg(gl, VS_SCREEN, FS_BLOOM_BRIGHT);
  const bloomCoProg = mkProg(gl, VS_SCREEN, FS_BLOOM_COMP);

  // ── Geometry buffers ──────────────────────────────────────────────────────
  const fullQuad = mkQuadBuf(gl, 0, 0, CW, CH);
  const cardQuad = mkQuadBuf(gl, CARD_X - 40, CARD_Y - 40, CARD_X + CARD_W + 40, CARD_Y + CARD_H + 40);
  const artQuad  = mkQuadBuf(gl, ART_X - 60, ART_Y - 60, ART_X + ART_W + 60, ART_Y + ART_H + 60);

  // Zigzag waveform triangle strip buffer (dynamic — rebuilt per frame)
  const zigBuf = gl.createBuffer()!;
  // Pre-compute zigzag points
  const zigPoints: [number, number][] = [[0, 15]];
  for (let i = 0; i < 80; i++) {
    zigPoints.push([ ((i+1)/80) * ZIG_W, i%2===0 ? 5 : 25 ]);
  }

  // ── FBOs ─────────────────────────────────────────────────────────────────
  const blurFBO1 = mkFBO(gl, CW, CH);
  const blurFBO2 = mkFBO(gl, CW, CH);
  const sceneFBO = mkFBO(gl, CW, CH); // used in upgraded mode for bloom
  const bloomFBO1= mkFBO(gl, CW, CH);
  const bloomFBO2= mkFBO(gl, CW, CH);
  const bloomFBO3= mkFBO(gl, CW, CH);

  // ── Load images ───────────────────────────────────────────────────────────
  const bgImg    = cfg.bgImageUrl    ? await loadImage(cfg.bgImageUrl)    : null;
  const coverImg = cfg.coverImageUrl ? await loadImage(cfg.coverImageUrl) : null;

  // ── Upload bg texture + pre-compute blur ──────────────────────────────────
  const bgTex = mkTex(gl);
  if (bgImg) {
    uploadImageToTex(gl, bgTex, bgImg);
  } else {
    // Solid dark colour as 1×1 texture
    gl.bindTexture(gl.TEXTURE_2D, bgTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
      new Uint8Array([dark[0], dark[1], dark[2], 255]));
  }

  // Two-pass Gaussian blur for background (sigma 20 = ~blur(40px) visual)
  const BLUR_SIGMA = 20;
  runBlurPass(gl, blurProg, fullQuad, bgTex,     blurFBO1, 1/CW, 0,    BLUR_SIGMA, CW, CH);
  runBlurPass(gl, blurProg, fullQuad, blurFBO1.tex, blurFBO2, 0, 1/CH, BLUR_SIGMA, CW, CH);
  const blurredBgTex = blurFBO2.tex; // final blurred bg

  // ── Cover textures ────────────────────────────────────────────────────────
  const coverTex = mkTex(gl);
  let hasCover = false;
  if (coverImg) {
    uploadImageToTex(gl, coverTex, coverImg);
    hasCover = true;
  }

  // Grayscale cover canvas for inferno (done once via Canvas 2D, uploaded)
  const grayCanvas = document.createElement("canvas");
  const infernoSqSize = Math.round(ART_W * 0.70);
  grayCanvas.width = infernoSqSize;
  grayCanvas.height = infernoSqSize;
  const grayCtx = grayCanvas.getContext("2d")!;
  if (coverImg) {
    const ratio = coverImg.width / coverImg.height;
    let dw = infernoSqSize, dh = infernoSqSize;
    if (ratio > 1) { dh = infernoSqSize; dw = ratio * infernoSqSize; }
    else           { dw = infernoSqSize; dh = infernoSqSize / ratio; }
    grayCtx.filter = "grayscale(1) contrast(1.25)";
    grayCtx.globalAlpha = 0.9;
    grayCtx.drawImage(coverImg, (infernoSqSize-dw)/2, (infernoSqSize-dh)/2, dw, dh);
    grayCtx.filter = "none"; grayCtx.globalAlpha = 1;
    const gf = grayCtx.createLinearGradient(0, infernoSqSize*0.5, 0, infernoSqSize);
    gf.addColorStop(0, "rgba(0,0,0,0)"); gf.addColorStop(1, "rgba(0,0,0,0.8)");
    grayCtx.fillStyle = gf; grayCtx.fillRect(0, 0, infernoSqSize, infernoSqSize);
  }
  const grayTex = mkTex(gl);
  uploadImageToTex(gl, grayTex, grayCanvas);

  // ── Text canvas (Canvas 2D → WebGL texture) ───────────────────────────────
  const textCanvas = document.createElement("canvas");
  textCanvas.width = CW; textCanvas.height = CH;
  const tctx = textCanvas.getContext("2d")!;
  const textTex = mkTex(gl);

  let lastGroupIdx = -999;
  let lastWordIdx  = -999;

  function renderTextCanvas(audioTime: number) {
    const tAbs = audioTime + (cfg.clipStartS ?? 0);
    let wi = -1;
    for (let i = 0; i < words.length; i++) {
      if (words[i].start_s <= tAbs) wi = i;
      else break;
    }
    const gi = wi >= 0 ? Math.floor(wi / GROUP_SZ) : 0;
    const li = wi >= 0 ? wi - gi * GROUP_SZ : -1;
    if (gi === lastGroupIdx && li === lastWordIdx) return; // no change
    lastGroupIdx = gi; lastWordIdx = li;

    tctx.clearRect(0, 0, CW, CH);

    // NOW PLAYING label
    const labelY = CARD_Y + CARD_H - 40;
    tctx.save();
    tctx.font = "bold 20px -apple-system,'Segoe UI',sans-serif";
    tctx.textBaseline = "middle";
    tctx.fillStyle = "rgba(255,255,255,0.50)";
    const text = "NOW PLAYING";
    const spacing = 6;
    let totalW = 0;
    for (const ch of text) totalW += tctx.measureText(ch).width + spacing;
    totalW -= spacing;
    let cx = CW/2 - totalW/2;
    for (const ch of text) {
      tctx.fillText(ch, cx, labelY);
      cx += tctx.measureText(ch).width + spacing;
    }
    tctx.restore();

    // Karaoke lyrics
    const groups: AudioWord[][] = [];
    for (let i = 0; i < words.length; i += GROUP_SZ) groups.push(words.slice(i, i + GROUP_SZ));
    const grp = groups[gi] ?? [];
    if (grp.length === 0) { uploadImageToTex(gl, textTex, textCanvas); return; }

    let fs = 80;
    tctx.font = `bold ${fs}px -apple-system,'Segoe UI',sans-serif`;
    tctx.textBaseline = "middle";
    const parts = grp.map((w, i) => w.word + (i < grp.length-1 ? " " : ""));
    let tw = parts.reduce((s, p) => s + tctx.measureText(p).width, 0);
    if (tw > CW * 0.87) {
      fs = Math.floor(fs * (CW * 0.87) / tw);
      tctx.font = `bold ${fs}px -apple-system,'Segoe UI',sans-serif`;
      tw = parts.reduce((s, p) => s + tctx.measureText(p).width, 0);
    }

    let x = CW/2 - tw/2;
    tctx.save();
    parts.forEach((p, i) => {
      const pw = tctx.measureText(p).width;
      if (i === li) {
        tctx.fillStyle = theme.accent;
        tctx.shadowColor = `rgba(${Math.round(acR*255)},${Math.round(acG*255)},${Math.round(acB*255)},0.75)`;
        tctx.shadowBlur = upgraded ? 40 : 28;
      } else if (i < li) {
        tctx.fillStyle = "rgba(255,255,255,0.40)";
        tctx.shadowBlur = 0;
      } else {
        tctx.fillStyle = "rgba(255,255,255,0.88)";
        tctx.shadowColor = "rgba(0,0,0,0.8)";
        tctx.shadowBlur = 10;
      }
      tctx.fillText(p, x, LYRIC_Y);
      x += pw;
      tctx.shadowBlur = 0;
    });
    tctx.restore();

    uploadImageToTex(gl, textTex, textCanvas);
  }

  // ── Particle attribute buffers ────────────────────────────────────────────
  const pSeeds = makeParticleSeeds(20);
  const fSeeds = makeFlameSeeds(15);

  function buildParticleAttrBuf(seeds: PSeed[]): WebGLBuffer {
    const data = new Float32Array(seeds.flatMap(s => [s.x, s.size, s.speed, s.delay, s.period, s.xDrift]));
    const buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return buf;
  }

  function buildFlameAttrBuf(seeds: FSeed[]): WebGLBuffer {
    const data = new Float32Array(seeds.flatMap(s => [s.x, s.w, s.h, s.speed, s.delay, s.period]));
    const buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return buf;
  }

  const partBuf = buildParticleAttrBuf(pSeeds);
  const flamBuf = buildFlameAttrBuf(fSeeds);

  // ── Zigzag triangle strip builder ─────────────────────────────────────────
  function buildZigzagStrip(progressFraction: number): { data: Float32Array; count: number } {
    const WIDTH = 4; // half-width of the stroke in pixels
    const verts: number[] = [];
    const maxI = Math.round(zigPoints.length * Math.max(0, Math.min(1, progressFraction)));
    for (let i = 0; i < maxI; i++) {
      const [px, py] = zigPoints[i];
      // Normal: perpendicular to the line direction
      const nx = ZIG_X + px;
      const ny = ZIG_Y - ZIG_H/2 + py;
      // Thicken along Y
      verts.push(nx, ny - WIDTH, nx, ny + WIDTH);
    }
    const data = new Float32Array(verts);
    return { data, count: verts.length / 2 };
  }

  // ── Draw helpers ──────────────────────────────────────────────────────────

  function bindTarget(target: WebGLFramebuffer | null) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, target);
    gl.viewport(0, 0, CW, CH);
  }

  function setRes(prog: WebGLProgram) {
    uni2f(gl, prog, "u_res", CW, CH);
  }

  // Draw background (blurred or solid)
  function drawBg() {
    gl.useProgram(blitProg);
    setRes(blitProg);
    uniTex(gl, blitProg, "u_tex", blurredBgTex, 0);
    uni1f(gl, blitProg, "u_alpha", 1.0);
    drawQuad(gl, blitProg, fullQuad);
  }

  // Draw gradient overlay
  function drawGradient() {
    gl.useProgram(gradProg);
    setRes(gradProg);
    uni3f(gl, gradProg, "u_dark", dark[0], dark[1], dark[2]);
    drawQuad(gl, gradProg, fullQuad);
  }

  // Draw template colour tints
  function drawTints() {
    gl.useProgram(radialProg);
    setRes(radialProg);
    if (tid === "vivid") {
      uni2f(gl, radialProg, "u_center", -200, -200);
      uni1f(gl, radialProg, "u_radius", 700);
      uni4f(gl, radialProg, "u_color", 1.0, 0.353, 0.784, 0.22);
      drawQuad(gl, radialProg, fullQuad);
    } else if (tid === "neon") {
      uni2f(gl, radialProg, "u_center", CW/2, CH*0.3);
      uni1f(gl, radialProg, "u_radius", 800);
      uni4f(gl, radialProg, "u_color", 0.0, 0.863, 1.0, 0.08);
      drawQuad(gl, radialProg, fullQuad);
    }
  }

  // Draw particles (screen blend)
  function drawParticles(t: number) {
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE); // screen-like additive
    gl.useProgram(partProg);
    gl.uniform1f(gl.getUniformLocation(partProg,"u_time"), t);
    uni2f(gl, partProg, "u_res", CW, CH);
    uni3f(gl, partProg, "u_color", acR, acG, acB);
    uni1f(gl, partProg, "u_upgraded", upgraded ? 1.0 : 0.0);

    const stride = 6 * 4; // 6 floats * 4 bytes
    gl.bindBuffer(gl.ARRAY_BUFFER, partBuf);
    const attrs = [
      ["a_x",0],["a_size",1],["a_speed",2],["a_delay",3],["a_period",4],["a_xdrift",5]
    ] as const;
    for (const [name, idx] of attrs) {
      const loc = gl.getAttribLocation(partProg, name);
      if (loc>=0) { gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,1,gl.FLOAT,false,stride,idx*4); }
    }
    gl.drawArrays(gl.POINTS, 0, pSeeds.length);
    for (const [name] of attrs) {
      const loc = gl.getAttribLocation(partProg, name);
      if (loc>=0) gl.disableVertexAttribArray(loc);
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  // Draw flames (screen blend, white)
  function drawFlames(t: number) {
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.useProgram(flameProg);
    gl.uniform1f(gl.getUniformLocation(flameProg,"u_time"), t);
    uni2f(gl, flameProg, "u_res", CW, CH);

    const stride = 6 * 4;
    gl.bindBuffer(gl.ARRAY_BUFFER, flamBuf);
    const attrs = [
      ["a_x",0],["a_w",1],["a_h",2],["a_speed",3],["a_delay",4],["a_period",5]
    ] as const;
    for (const [name, idx] of attrs) {
      const loc = gl.getAttribLocation(flameProg, name);
      if (loc>=0) { gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,1,gl.FLOAT,false,stride,idx*4); }
    }
    gl.drawArrays(gl.POINTS, 0, fSeeds.length);
    for (const [name] of attrs) {
      const loc = gl.getAttribLocation(flameProg, name);
      if (loc>=0) gl.disableVertexAttribArray(loc);
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  // Draw frosted glass card
  function drawCard() {
    // Fill (frosted glass from blurred bg)
    gl.useProgram(cardFillProg);
    setRes(cardFillProg);
    uniTex(gl, cardFillProg, "u_blur", blurredBgTex, 0);
    uni2f(gl, cardFillProg, "u_card_pos",  CARD_X, CARD_Y);
    uni2f(gl, cardFillProg, "u_card_size", CARD_W, CARD_H);
    uni1f(gl, cardFillProg, "u_card_r",    CARD_R);
    // Theme tint
    if      (tid==="minimal") uni4f(gl, cardFillProg, "u_tint", 10/255, 12/255, 18/255, 0.55);
    else if (tid==="vivid")   uni4f(gl, cardFillProg, "u_tint", 26/255, 0, 36/255, 0.55);
    else if (tid==="neon")    uni4f(gl, cardFillProg, "u_tint", 0, 0, 0, 0.55);
    else                      uni4f(gl, cardFillProg, "u_tint", 8/255, 6/255, 6/255, 0.55);
    drawQuad(gl, cardFillProg, cardQuad);

    // Border + optional glow
    gl.useProgram(cardBordProg);
    setRes(cardBordProg);
    uni2f(gl, cardBordProg, "u_card_pos",  CARD_X, CARD_Y);
    uni2f(gl, cardBordProg, "u_card_size", CARD_W, CARD_H);
    uni1f(gl, cardBordProg, "u_card_r",    CARD_R);
    uni1f(gl, cardBordProg, "u_border_w",  2.0);
    if (tid==="minimal")     { uni4f(gl,cardBordProg,"u_border_color",1,1,1,0.10); uni4f(gl,cardBordProg,"u_glow_color",0,0,0,0); uni1f(gl,cardBordProg,"u_glow_r",0); }
    else if (tid==="vivid")  { uni4f(gl,cardBordProg,"u_border_color",1,0.353,0.784,0.30); uni4f(gl,cardBordProg,"u_glow_color",0,0,0,0); uni1f(gl,cardBordProg,"u_glow_r",0); }
    else if (tid==="neon")   { uni4f(gl,cardBordProg,"u_border_color",0,0.863,1,0.40); uni4f(gl,cardBordProg,"u_glow_color",0,0.863,1,1.0); uni1f(gl,cardBordProg,"u_glow_r",upgraded?60:40); }
    else                     { uni4f(gl,cardBordProg,"u_border_color",1,1,1,0.20); uni4f(gl,cardBordProg,"u_glow_color",0,0,0,0); uni1f(gl,cardBordProg,"u_glow_r",0); }
    drawQuad(gl, cardBordProg, cardQuad);
  }

  // ── Theme art draw functions ───────────────────────────────────────────────

  function drawMinimalArt(t: number) {
    // Center glow
    gl.useProgram(radialProg);
    setRes(radialProg);
    uni2f(gl, radialProg, "u_center", ART_CX, ART_CY);
    uni1f(gl, radialProg, "u_radius", ART_R * 0.40);
    uni4f(gl, radialProg, "u_color", 0, 1, 0.667, 0.20);
    drawQuad(gl, radialProg, artQuad);

    // Outer dashed ring (rotating CW, 20s)
    gl.useProgram(ringProg);
    setRes(ringProg);
    uni2f(gl, ringProg, "u_center", ART_CX, ART_CY);
    uni1f(gl, ringProg, "u_r_inner", ART_R*0.85 - 1);
    uni1f(gl, ringProg, "u_r_outer", ART_R*0.85 + 1);
    uni4f(gl, ringProg, "u_color", 0, 1, 0.667, 0.50);
    uni1f(gl, ringProg, "u_dash_count", 12);
    uni1f(gl, ringProg, "u_rot", (t * Math.PI * 2) / 20);
    drawQuad(gl, ringProg, artQuad);

    // Inner solid ring (CCW, 15s)
    uni1f(gl, ringProg, "u_r_inner", ART_R*0.65 - 1);
    uni1f(gl, ringProg, "u_r_outer", ART_R*0.65 + 2);
    uni4f(gl, ringProg, "u_color", 0, 1, 0.667, 0.40);
    uni1f(gl, ringProg, "u_dash_count", 0);
    uni1f(gl, ringProg, "u_rot", -(t * Math.PI * 2) / 15);
    drawQuad(gl, ringProg, artQuad);

    // Album cover (pulsing)
    const coverScale = 1 + 0.03 * Math.sin((Math.PI * 2 * t) / 1.5);
    const coverR = Math.round(ART_R * 0.45);
    if (hasCover) {
      // Shadow/glow ring (upgraded)
      if (upgraded) {
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
        uni2f(gl, ringProg, "u_center", ART_CX, ART_CY);
        uni1f(gl, ringProg, "u_r_inner", coverR * coverScale);
        uni1f(gl, ringProg, "u_r_outer", coverR * coverScale + 30);
        uni4f(gl, ringProg, "u_color", 0, 1, 0.667, 0.15);
        uni1f(gl, ringProg, "u_dash_count", 0);
        drawQuad(gl, ringProg, artQuad);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      }
      gl.useProgram(coverCirProg);
      setRes(coverCirProg);
      uni2f(gl, coverCirProg, "u_center", ART_CX, ART_CY);
      uni1f(gl, coverCirProg, "u_radius", coverR);
      uni1f(gl, coverCirProg, "u_scale",  coverScale);
      uni4f(gl, coverCirProg, "u_tint",   0, 0, 0, 0);
      uniTex(gl, coverCirProg, "u_tex",   coverTex, 0);
      drawQuad(gl, coverCirProg, artQuad);
    }
  }

  function drawVividArt(t: number) {
    function lerp4(frac: number, dur: number, vals: number[]): number {
      const ph = ((frac % dur) + dur) % dur;
      const sc = vals.length - 1, sd = dur / sc;
      const si = Math.min(Math.floor(ph / sd), sc - 1);
      const st = (ph - si * sd) / sd;
      return vals[si] + (vals[si+1] - vals[si]) * st;
    }
    // Pink blob (top-left)
    const bx1 = lerp4(t, 5, [0,60,-60,0]);
    const by1 = lerp4(t, 5, [0,-80,60,0]);
    const bs1 = lerp4(t, 5, [1,1.5,1,1]);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.useProgram(radialProg);
    setRes(radialProg);
    uni2f(gl, radialProg, "u_center", ART_X + bx1, ART_Y + by1);
    uni1f(gl, radialProg, "u_radius", 96 * bs1);
    uni4f(gl, radialProg, "u_color", 1.0, 0.353, 0.784, 0.70);
    drawQuad(gl, radialProg, artQuad);
    // Purple blob (bottom-right)
    const bx2 = lerp4(t, 4, [0,-80,40,0]);
    const by2 = lerp4(t, 4, [0,60,-80,0]);
    const bs2 = lerp4(t, 4, [1,1.2,1,1]);
    uni2f(gl, radialProg, "u_center", ART_X + ART_W + bx2, ART_Y + ART_H + by2);
    uni1f(gl, radialProg, "u_radius", 112 * bs2);
    uni4f(gl, radialProg, "u_color", 0.659, 0.333, 0.969, 0.70);
    drawQuad(gl, radialProg, artQuad);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // Album cover (rounded rect, pulsing)
    const vScale = 1 + 0.15 * Math.sin((Math.PI * 2 * t) / 0.6);
    const vSz = Math.round(ART_R * 1.1) * vScale;
    const vx = ART_CX - vSz/2, vy = ART_CY - vSz/2;
    if (hasCover) {
      gl.useProgram(coverRRProg);
      setRes(coverRRProg);
      uni2f(gl, coverRRProg, "u_pos",    vx, vy);
      uni2f(gl, coverRRProg, "u_size",   vSz, vSz);
      uni1f(gl, coverRRProg, "u_corner", 36);
      uni4f(gl, coverRRProg, "u_tint",   1.0, 0.353, 0.784, 0.30);
      uniTex(gl, coverRRProg, "u_tex",   coverTex, 0);
      drawQuad(gl, coverRRProg, artQuad);
    }
  }

  function drawNeonArt(t: number) {
    const spinAngle = (t * Math.PI * 2) / 5;   // vinyl spin
    const discR = ART_R * 0.85;
    const coverR = discR * 0.265;

    // Vinyl shader
    gl.useProgram(vinylProg);
    setRes(vinylProg);
    uni2f(gl, vinylProg, "u_center", ART_CX, ART_CY);
    uni1f(gl, vinylProg, "u_disc_r",  discR);
    uni1f(gl, vinylProg, "u_spin",    spinAngle);
    uni1f(gl, vinylProg, "u_cover_r", coverR);
    uni3f(gl, vinylProg, "u_accent",  0, 0.863, 1.0);
    drawQuad(gl, vinylProg, artQuad);

    // Center album cover inside disc
    if (hasCover) {
      gl.useProgram(coverCirProg);
      setRes(coverCirProg);
      uni2f(gl, coverCirProg, "u_center", ART_CX, ART_CY);
      uni1f(gl, coverCirProg, "u_radius", coverR);
      uni1f(gl, coverCirProg, "u_scale",  1.0);
      uni4f(gl, coverCirProg, "u_tint",   0, 0, 0, 0);
      uniTex(gl, coverCirProg, "u_tex",   coverTex, 0);
      drawQuad(gl, coverCirProg, artQuad);
    }

    // Center dot
    gl.useProgram(ringProg);
    setRes(ringProg);
    uni2f(gl, ringProg, "u_center",  ART_CX, ART_CY);
    uni1f(gl, ringProg, "u_r_inner", 0);
    uni1f(gl, ringProg, "u_r_outer", 8);
    uni4f(gl, ringProg, "u_color",   0, 0, 0, 1.0);
    uni1f(gl, ringProg, "u_dash_count", 0);
    uni1f(gl, ringProg, "u_rot",     0);
    drawQuad(gl, ringProg, artQuad);
    // Neon dot ring
    uni1f(gl, ringProg, "u_r_inner", 7);
    uni1f(gl, ringProg, "u_r_outer", 10);
    uni4f(gl, ringProg, "u_color",   0, 0.863, 1.0, 0.60);
    drawQuad(gl, ringProg, artQuad);
  }

  function drawInfernoArt(t: number) {
    // Flames inside art area (already drawn globally, art clip optional)
    drawFlames(t);

    // Bobbing cover
    const bobY = -10 * Math.sin((Math.PI * 2 * t) / 2);
    const sqSz = infernoSqSize;
    const sx = ART_CX - sqSz/2, sy = ART_CY - sqSz/2 + bobY;

    // White border bg
    gl.useProgram(cardFillProg); // reuse fill prog as a tinted rect
    setRes(cardFillProg);
    uniTex(gl, cardFillProg, "u_blur", blurredBgTex, 0);
    uni2f(gl, cardFillProg, "u_card_pos",  sx-4, sy-4);
    uni2f(gl, cardFillProg, "u_card_size", sqSz+8, sqSz+8);
    uni1f(gl, cardFillProg, "u_card_r",    0);
    uni4f(gl, cardFillProg, "u_tint",      0, 0, 0, 1.0); // fully opaque black
    const borderQuad = mkQuadBuf(gl, sx-8, sy-8, sx+sqSz+8, sy+sqSz+8);
    drawQuad(gl, cardFillProg, borderQuad);

    // Grayscale cover
    if (coverImg) {
      gl.useProgram(blitProg);
      setRes(blitProg);
      uniTex(gl, blitProg, "u_tex", grayTex, 0);
      uni1f(gl, blitProg, "u_alpha", 1.0);
      const covQuad = mkQuadBuf(gl, sx, sy, sx+sqSz, sy+sqSz);
      drawQuad(gl, blitProg, covQuad);
    }
  }

  // Zigzag waveform
  function drawZigzag(audioTime: number) {
    const progress = Math.min(1, Math.max(0, audioTime / cfg.clipDuration));

    // Background (dim white)
    const { data: bgData, count: bgCount } = buildZigzagStrip(1.0);
    gl.useProgram(zigProg);
    setRes(zigProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, zigBuf);
    gl.bufferData(gl.ARRAY_BUFFER, bgData, gl.DYNAMIC_DRAW);
    const loc = gl.getAttribLocation(zigProg, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    uni3f(gl, zigProg, "u_color", 1, 1, 1);
    uni1f(gl, zigProg, "u_alpha", 0.15);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, bgCount);

    // Foreground (accent colored, clipped to progress)
    const { data: fgData, count: fgCount } = buildZigzagStrip(progress);
    gl.bufferData(gl.ARRAY_BUFFER, fgData, gl.DYNAMIC_DRAW);
    uni3f(gl, zigProg, "u_color", acR, acG, acB);
    uni1f(gl, zigProg, "u_alpha", upgraded ? 0.9 : 0.85);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, fgCount);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disableVertexAttribArray(loc);
  }

  // Text overlay composite
  function drawText() {
    gl.useProgram(blitProg);
    setRes(blitProg);
    uniTex(gl, blitProg, "u_tex", textTex, 0);
    uni1f(gl, blitProg, "u_alpha", 1.0);
    drawQuad(gl, blitProg, fullQuad);
  }

  // ── Bloom post-processing (upgraded mode only) ─────────────────────────────
  function applyBloom() {
    // 1. Extract bright pixels
    gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFBO1.fbo);
    gl.viewport(0, 0, CW, CH);
    gl.useProgram(bloomBrProg);
    setRes(bloomBrProg);
    uniTex(gl, bloomBrProg, "u_tex", sceneFBO.tex, 0);
    uni1f(gl, bloomBrProg, "u_threshold", 0.65);
    drawQuad(gl, bloomBrProg, fullQuad);

    // 2. Blur horizontally
    runBlurPass(gl, blurProg, fullQuad, bloomFBO1.tex, bloomFBO2, 2/CW, 0, 8, CW, CH);
    // 3. Blur vertically
    runBlurPass(gl, blurProg, fullQuad, bloomFBO2.tex, bloomFBO3, 0, 2/CH, 8, CW, CH);

    // 4. Composite bloom onto main canvas
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, CW, CH);
    gl.useProgram(bloomCoProg);
    setRes(bloomCoProg);
    uniTex(gl, bloomCoProg, "u_scene", sceneFBO.tex, 0);
    uniTex(gl, bloomCoProg, "u_bloom", bloomFBO3.tex, 1);
    uni1f(gl, bloomCoProg, "u_strength", 0.8);
    drawQuad(gl, bloomCoProg, fullQuad);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  PUBLIC API
  // ══════════════════════════════════════════════════════════════════════════

  function renderFrame(audioCurrentTime: number) {
    // Update text texture if word changed
    renderTextCanvas(audioCurrentTime);

    // In upgraded mode, render scene to FBO for bloom
    const target = upgraded ? sceneFBO.fbo : null;
    bindTarget(target);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);

    // 1. Background
    drawBg();

    // 2. Gradient overlay
    drawGradient();

    // 3. Template tints
    drawTints();

    // 4. Particles or flames (behind card)
    if (tid === "inferno") {
      drawFlames(audioCurrentTime);
    } else {
      drawParticles(audioCurrentTime);
    }

    // 5. Card frosted glass
    drawCard();

    // 6. Template art inside card
    switch (tid) {
      case "minimal": drawMinimalArt(audioCurrentTime); break;
      case "vivid":   drawVividArt(audioCurrentTime);   break;
      case "neon":    drawNeonArt(audioCurrentTime);    break;
      case "inferno": drawInfernoArt(audioCurrentTime); break;
    }

    // 7. Zigzag waveform
    drawZigzag(audioCurrentTime);

    // 8. Text overlay (karaoke + NOW PLAYING)
    drawText();

    // 9. Bloom pass (upgraded only)
    if (upgraded) {
      applyBloom();
    }
  }

  function destroy() {
    gl.deleteBuffer(fullQuad);
    gl.deleteBuffer(cardQuad);
    gl.deleteBuffer(artQuad);
    gl.deleteBuffer(zigBuf);
    gl.deleteBuffer(partBuf);
    gl.deleteBuffer(flamBuf);
    for (const tex of [bgTex, coverTex, grayTex, textTex,
                       blurFBO1.tex, blurFBO2.tex,
                       sceneFBO.tex, bloomFBO1.tex, bloomFBO2.tex, bloomFBO3.tex]) {
      gl.deleteTexture(tex);
    }
    for (const { fbo } of [blurFBO1, blurFBO2, sceneFBO, bloomFBO1, bloomFBO2, bloomFBO3]) {
      gl.deleteFramebuffer(fbo);
    }
    const ext = gl.getExtension("WEBGL_lose_context");
    ext?.loseContext();
  }

  return { canvas, renderFrame, destroy };
}
