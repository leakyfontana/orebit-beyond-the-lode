shader_type canvas_item;
render_mode unshaded, blend_premul_alpha;

// Import-time material conversion of TMP_SDF.shader / TMPro.cginc. Label still
// owns glyph shaping, positioning and drawing; TEXTURE is its native SDF atlas.
uniform sampler2D glyph_bounds : filter_nearest, repeat_disable;
uniform sampler2D face_texture : source_color, hint_default_white, filter_linear, repeat_enable;
uniform sampler2D outline_texture : source_color, hint_default_white, filter_linear, repeat_enable;
uniform vec4 face_uv = vec4(1.0, 1.0, 0.0, 0.0);
uniform vec4 outline_uv = vec4(1.0, 1.0, 0.0, 0.0);
uniform vec4 _FaceColor : source_color = vec4(1.0);
uniform vec4 _OutlineColor : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform vec4 _SpecularColor : source_color = vec4(1.0);
uniform vec4 _GlowColor : source_color = vec4(0.0, 1.0, 0.0, 0.5);
uniform vec4 _UnderlayColor : source_color = vec4(0.0, 0.0, 0.0, 0.5);
uniform float _GradientScale = 5.0;
uniform float _ScaleRatioA = 1.0;
uniform float _ScaleRatioB = 1.0;
uniform float _ScaleRatioC = 1.0;
uniform float source_weight = 0.0;
uniform float _OutlineWidth = 0.0;
uniform float _OutlineSoftness = 0.0;
uniform float _Sharpness = 0.0;
uniform float _Bevel = 0.0;
uniform float _BevelOffset = 0.0;
uniform float _BevelWidth = 0.0;
uniform float _BevelClamp = 0.0;
uniform float _BevelRoundness = 0.0;
uniform float _ShaderFlags = 0.0;
uniform float _LightAngle = 3.141592;
uniform float _Reflectivity = 10.0;
uniform float _SpecularPower = 1.0;
uniform float _Diffuse = 0.5;
uniform float _Ambient = 0.5;
uniform float _GlowOffset = 0.0;
uniform float _GlowInner = 0.05;
uniform float _GlowOuter = 0.05;
uniform float _GlowPower = 0.75;
uniform float _UnderlayOffsetX = 0.0;
uniform float _UnderlayOffsetY = 0.0;
uniform float _UnderlayDilate = 0.0;
uniform float _UnderlaySoftness = 0.0;
uniform bool bevel_on = false;
uniform bool glow_on = false;
uniform bool underlay_on = false;
uniform bool underlay_inner = false;
varying vec4 vertex_color;

void vertex() {
	vertex_color = COLOR;
}

vec3 surface_normal(vec4 h) {
	h += vec4(source_weight + _BevelOffset);
	float width = max(0.01, _OutlineWidth + _BevelWidth);
	h = clamp((h - vec4(0.5)) / width + vec4(0.5), vec4(0.0), vec4(1.0));
	if (mod(_ShaderFlags, 2.0) >= 1.0) {
		h = vec4(1.0) - abs(h * 2.0 - vec4(1.0));
	}
	h = mix(h, sin(h * 3.141592 / 2.0), _BevelRoundness);
	h = min(h, vec4(1.0 - _BevelClamp));
	h *= _Bevel * width * _GradientScale * -2.0;
	return cross(normalize(vec3(1.0, 0.0, h.y - h.x)), normalize(vec3(0.0, -1.0, h.w - h.z)));
}

void fragment() {
	vec2 atlas_size = vec2(textureSize(TEXTURE, 0));
	vec2 dx = dFdx(UV) * atlas_size;
	vec2 dy = dFdy(UV) * atlas_size;
	// TMP orthographic pixelSize / glyph scale, including native canvas scale.
	float scale = 2.0 * _GradientScale * (_Sharpness + 1.0) / max(0.000001, sqrt(dot(dx, dx) + dot(dy, dy)));
	float distance_value = texture(TEXTURE, UV).r;
	float bias = 0.5 - source_weight + 0.5 / scale;
	float sd = (bias - distance_value) * scale;
	float outline = _OutlineWidth * _ScaleRatioA * scale;
	float softness = _OutlineSoftness * _ScaleRatioA * scale;
	vec4 bounds = texture(glyph_bounds, UV);
	vec2 character_uv = (UV - bounds.xy) / max(bounds.zw, vec2(0.000001));
	vec4 face = _FaceColor * texture(face_texture, character_uv * face_uv.xy + face_uv.zw);
	vec4 edge = _OutlineColor * texture(outline_texture, character_uv * outline_uv.xy + outline_uv.zw);
	// Source vertex RGB affects the face only. Vertex alpha fades the entire
	// premultiplied result, including outline, underlay and glow, at the end.
	face.rgb *= vertex_color.rgb;
	face.rgb *= face.a;
	edge.rgb *= edge.a;
	float face_alpha = 1.0 - clamp((sd - outline * 0.5 + softness * 0.5) / (1.0 + softness), 0.0, 1.0);
	float outline_alpha = clamp(sd + outline * 0.5, 0.0, 1.0) * sqrt(min(1.0, outline));
	vec4 result = mix(face, edge, outline_alpha) * face_alpha;
	if (bevel_on) {
		vec2 texel = 0.5 / atlas_size;
		vec3 n = surface_normal(vec4(
			texture(TEXTURE, UV - vec2(texel.x, 0.0)).r,
			texture(TEXTURE, UV + vec2(texel.x, 0.0)).r,
			texture(TEXTURE, UV - vec2(0.0, texel.y)).r,
			texture(TEXTURE, UV + vec2(0.0, texel.y)).r));
		vec3 light = normalize(vec3(sin(_LightAngle), cos(_LightAngle), -1.0));
		vec3 specular = _SpecularColor.rgb * pow(max(0.0, dot(n, light)), _Reflectivity) * _SpecularPower;
		result.rgb += specular * result.a;
		result.rgb *= 1.0 - dot(n, light) * _Diffuse;
		result.rgb *= mix(_Ambient, 1.0, n.z * n.z);
	}
	if (underlay_on || underlay_inner) {
		float layer_scale = scale / (1.0 + _UnderlaySoftness * _ScaleRatioC * scale);
		float layer_bias = (0.5 - source_weight) * layer_scale - 0.5 - _UnderlayDilate * _ScaleRatioC * 0.5 * layer_scale;
		vec2 offset = vec2(-_UnderlayOffsetX, _UnderlayOffsetY) * _ScaleRatioC * _GradientScale / atlas_size;
		float d = texture(TEXTURE, UV + offset).r * layer_scale;
		float coverage = underlay_inner ? (1.0 - clamp(d - layer_bias, 0.0, 1.0)) * clamp(1.0 - sd, 0.0, 1.0) : clamp(d - layer_bias, 0.0, 1.0);
		result += vec4(_UnderlayColor.rgb * _UnderlayColor.a, _UnderlayColor.a) * coverage * (1.0 - result.a);
	}
	if (glow_on) {
		float glow = sd - _GlowOffset * _ScaleRatioB * 0.5 * scale;
		float t = mix(_GlowInner, _GlowOuter * _ScaleRatioB, step(0.0, glow)) * 0.5 * scale;
		glow = 1.0 - pow(clamp(abs(glow / (1.0 + t)), 0.0, 1.0), _GlowPower);
		glow *= sqrt(min(1.0, t));
		result.rgb += _GlowColor.rgb * clamp(_GlowColor.a * glow * 2.0, 0.0, 1.0);
	}
	COLOR = result * vertex_color.a;
}
