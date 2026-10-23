// Relations in the graph: the color doubles as the legend (colored checkboxes above the graph).
// A separate file, because both the graph and the “Relations” list use them.
export const RELATIONS = {
  similar: { label: 'Similar', color: '#f59e0b', dash: null },
  contains: { label: 'Contains', color: '#c084fc', dash: [2, 3] },
  same_name: { label: 'Same name', color: '#2dd4bf', dash: [6, 4] },
  is_type: { label: 'File type', color: 'rgba(200,200,200,0.35)', dash: null },
};
