# ISBERD and ISBEWR review

Upstream PR [#173](https://github.com/Djihads80/Eglantine/pull/173) adds ISBERD lowering and drops ISBEWR writes.
Do not treat the dropped writes as correct without a guest behavior test.

The Mario Kart World run `D:/DEV/egl-compare/nx2-nov01-guarded-mkw-c` rejected both opcodes.
One rejected ISBERD instruction has these 32-bit words:

```text
ff047923 00000000 00007800 000e2800
```

NVIDIA `nvdisasm` 12.6.20 identifies it as `ISBERD.ATTR.SKEW.32 R4, [RZ]`.
The PR maps this instruction to Maxwell word `efd000268007ff04`.
The local Maxwell translator declares the immediate as bits 24–31 and skew as bit 31.
For that word, it reads an immediate of `0x80` while skew is enabled.
The original native instruction has an immediate of zero.
This shows a field overlap in the local translator; it does not prove the rendered result.

The translator also converts an `IR::U32` index to `IR::Patch` or `IR::Attribute` in other ISBERD modes.
Those conversions require the corresponding IR value type. Test those paths before accepting them.

Mesa documents ISBE regions and skew at <https://docs.mesa3d.org/drivers/nvk/isbe_layout.html>.
Keep the current rejection for unsupported forms until the read and write semantics have focused tests.
