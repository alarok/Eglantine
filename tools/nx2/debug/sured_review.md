# SURED compute rejection

The Mario Kart World run `D:/DEV/egl-compare/nx2-nov01-guarded-mkw-c` rejected one compute program.
The same rejected dispatch was logged twice. The first unsupported instruction was:

```text
0400759f 60000c00 0010e000 000fe200
```

NVIDIA `nvdisasm` 12.6.20 identifies it as:

```text
SURED.D.2D.ADD.STRONG.GPU.IGN [R4], R0, 0x0, 0xc
```

`fixtures/sured_reduce.ptx` defines an independent sample-addressed 2D surface reduction.
Compile it with CUDA 12.6 `ptxas` for `sm_50` and `sm_86`.
Use `nvdisasm -hex` to inspect each output.
The reference files from this investigation are in `D:/DEV/egl-compare/sured-ptx-probe`.

The SM50 output uses `SURED.D.2D.ADD.IGN`.
The SM86 output uses `SURED.D.2D.ADD.STRONG.SYS.IGN`.
The compiled instruction uses system scope; the game instruction uses GPU scope.
These outputs help compare fields. They do not prove that the emulator preserves memory ordering.

The Maxwell SURED translator has unconfirmed field offsets.
The Vulkan backend uses a device-scope image atomic with relaxed memory semantics.
Before adding the native opcode, validate descriptor addressing, coordinate units, format, and ordering.
Run the operation against a known image and compare all affected texels.
Do not replace the reduction with a no-op.

Reference: [NVIDIA PTX surface reduction](https://docs.nvidia.com/cuda/parallel-thread-execution/#surface-instructions-sured).
