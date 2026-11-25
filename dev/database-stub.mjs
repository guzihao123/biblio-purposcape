export const database = {
  transaction: async (work) => work({
    query: async () => ({ rows: [] }),
  }),
};
