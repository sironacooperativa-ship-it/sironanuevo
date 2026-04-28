// Demo/mock data for Sirona preview (no backend calls).
// This file is intentionally standalone so it can be used by static mockups.

window.SIRONA_MOCK = {
  productos: [
    {
      codigo: "AC0001",
      descripcion: "Producto Demo 1",
      tipo: "Accesorios",
      proveedor: "DISMAR",
      costo: "$ 3.700,00",
      stock: 200,
      margen_pct: "31,0%",
      precio: "$ 3.315,00",
      estado: "Activo",
    },
    {
      codigo: "ME0052",
      descripcion: "Producto Demo 2",
      tipo: "Medicamentos",
      proveedor: "SAVANT",
      costo: "$ 955,50",
      stock: 959,
      margen_pct: "28,0%",
      precio: "$ 1.190,00",
      estado: "Activo",
    },
  ],
  clientes: [{ nombre: "Cliente Demo" }, { nombre: "Cliente Demo 2" }],
  vendedores: [{ nombre: "Vendedor Demo" }],
};

