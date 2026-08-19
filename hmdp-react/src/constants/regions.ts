export interface CommunityOption {
  label: string;
  value: string;
  children?: CommunityOption[];
}

interface BoroughDefinition {
  value: string;
  labelZh: string;
  communities: string[];
}

// Canonical values stay in English for backend compatibility. Only labels are localized.
const boroughs: BoroughDefinition[] = [
  {
    value: 'Manhattan',
    labelZh: '曼哈顿',
    communities: [
      'Battery Park City', 'Chelsea', 'Chinatown', 'Civic Center', 'East Harlem',
      'East Village', 'Financial District', 'Flatiron District', 'Gramercy Park',
      'Greenwich Village', 'Harlem', "Hell's Kitchen", 'Inwood', 'Little Italy',
      'Lower East Side', 'Midtown', 'Morningside Heights', 'NoHo', 'Nolita', 'SoHo',
      'Tribeca', 'Upper East Side', 'Upper West Side', 'Washington Heights', 'West Village',
    ],
  },
  {
    value: 'Brooklyn',
    labelZh: '布鲁克林',
    communities: [
      'Bay Ridge', 'Bedford-Stuyvesant', 'Bensonhurst', 'Boerum Hill', 'Borough Park',
      'Brighton Beach', 'Brooklyn Heights', 'Brownsville', 'Bushwick', 'Carroll Gardens',
      'Clinton Hill', 'Cobble Hill', 'Coney Island', 'Crown Heights', 'Downtown Brooklyn',
      'DUMBO', 'East New York', 'Flatbush', 'Fort Greene', 'Gowanus', 'Greenpoint',
      'Park Slope', 'Prospect Heights', 'Red Hook', 'Sheepshead Bay', 'Sunset Park',
      'Williamsburg',
    ],
  },
  {
    value: 'Queens',
    labelZh: '皇后区',
    communities: [
      'Astoria', 'Bayside', 'Corona', 'Elmhurst', 'Far Rockaway', 'Flushing',
      'Forest Hills', 'Fresh Meadows', 'Glendale', 'Jackson Heights', 'Jamaica',
      'Kew Gardens', 'Long Island City', 'Maspeth', 'Middle Village', 'Ozone Park',
      'Queens Village', 'Rego Park', 'Ridgewood', 'Rockaway Beach', 'Sunnyside',
      'Whitestone', 'Woodhaven', 'Woodside',
    ],
  },
  {
    value: 'Bronx',
    labelZh: '布朗克斯',
    communities: [
      'Belmont', 'City Island', 'Concourse', 'East Tremont', 'Fordham', 'Highbridge',
      'Hunts Point', 'Kingsbridge', 'Melrose', 'Morris Park', 'Mott Haven', 'Norwood',
      'Parkchester', 'Pelham Bay', 'Riverdale', 'Soundview', 'Throgs Neck',
      'University Heights', 'Wakefield', 'West Farms', 'Williamsbridge',
    ],
  },
  {
    value: 'Staten Island',
    labelZh: '史泰登岛',
    communities: [
      'Arrochar', 'Bay Terrace', 'Bulls Head', 'Castleton Corners', 'Clifton',
      'Dongan Hills', 'Eltingville', 'Great Kills', 'Grymes Hill', 'Huguenot',
      'New Dorp', 'New Springville', 'Oakwood', 'Port Richmond', "Prince's Bay",
      'Rosebank', 'St. George', 'Stapleton', 'Todt Hill', 'Tompkinsville',
      'Tottenville', 'West Brighton',
    ],
  },
];

export function getCommunityOptions(language: string): CommunityOption[] {
  const chinese = language.startsWith('zh');
  return boroughs.map((borough) => ({
    label: chinese ? borough.labelZh : borough.value,
    value: borough.value,
    children: borough.communities.map((community) => ({
      label: community,
      value: community,
    })),
  }));
}

export const communityCount = boroughs.reduce(
  (total, borough) => total + borough.communities.length,
  0,
);
