/*
 * PROJECT:     Okno OS
 * LICENSE:     GPL-2.0-or-later (https://spdx.org/licenses/GPL-2.0-or-later)
 * PURPOSE:     Out-of-line x86 float math for Clang
 *
 * math.h defines these as gnu_inline wrappers over the double functions, and the
 * x86 CRT DLLs (like Microsoft's) do not export them. Clang does not inline
 * gnu_inline bodies of library builtins, so modules need real definitions.
 */

#define _CRTBLD
#include <math.h>

float _chgsignf(float x) { return (float)_chgsign(x); }
float _copysignf(float x, float y) { return (float)_copysign(x, y); }
float _hypotf(float x, float y) { return (float)_hypot(x, y); }
float acosf(float x) { return (float)acos(x); }
float asinf(float x) { return (float)asin(x); }
float atanf(float x) { return (float)atan(x); }
float atan2f(float x, float y) { return (float)atan2(x, y); }
float ceilf(float x) { return (float)ceil(x); }
float cosf(float x) { return (float)cos(x); }
float coshf(float x) { return (float)cosh(x); }
float expf(float x) { return (float)exp(x); }
float floorf(float x) { return (float)floor(x); }
float fmodf(float x, float y) { return (float)fmod(x, y); }
float logf(float x) { return (float)log(x); }
float log10f(float x) { return (float)log10(x); }
float modff(float x, float *y) { double i, f = modf(x, &i); *y = (float)i; return (float)f; }
float powf(float x, float y) { return (float)pow(x, y); }
float sinf(float x) { return (float)sin(x); }
float sinhf(float x) { return (float)sinh(x); }
float sqrtf(float x) { return (float)sqrt(x); }
float tanf(float x) { return (float)tan(x); }
float tanhf(float x) { return (float)tanh(x); }
