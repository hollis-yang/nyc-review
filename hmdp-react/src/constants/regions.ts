// NYC borough/neighborhood cascade used by the profile editor.
const regions = [
  {
    label: 'Manhattan',
    value: 'Manhattan',
    children: [
      { label: 'Midtown', value: 'Midtown' },
      { label: 'Chelsea', value: 'Chelsea' },
      { label: 'SoHo', value: 'SoHo' },
      { label: 'East Village', value: 'East Village' },
      { label: 'Upper West Side', value: 'Upper West Side' },
      { label: 'Harlem', value: 'Harlem' },
    ],
  },
  {
    label: 'Brooklyn',
    value: 'Brooklyn',
    children: [
      { label: 'Williamsburg', value: 'Williamsburg' },
      { label: 'DUMBO', value: 'DUMBO' },
      { label: 'Park Slope', value: 'Park Slope' },
      { label: 'Bushwick', value: 'Bushwick' },
      { label: 'Coney Island', value: 'Coney Island' },
    ],
  },
  {
    label: 'Queens',
    value: 'Queens',
    children: [
      { label: 'Long Island City', value: 'Long Island City' },
      { label: 'Astoria', value: 'Astoria' },
      { label: 'Flushing', value: 'Flushing' },
      { label: 'Jackson Heights', value: 'Jackson Heights' },
    ],
  },
  {
    label: 'Bronx',
    value: 'Bronx',
    children: [
      { label: 'Fordham', value: 'Fordham' },
      { label: 'Riverdale', value: 'Riverdale' },
      { label: 'Mott Haven', value: 'Mott Haven' },
    ],
  },
  {
    label: 'Staten Island',
    value: 'Staten Island',
    children: [
      { label: 'St. George', value: 'St. George' },
      { label: 'New Dorp', value: 'New Dorp' },
    ],
  },
];

export default regions;
