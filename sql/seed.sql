INSERT INTO fields (field_name, description) VALUES
    ('Data and AI', 'Data scientist, machine learning engineer or data analyst: building and training models, data analysis, statistics, deep learning, natural language processing, Python, SQL, dashboards.'),
    ('Software Engineering', 'Software engineer or developer: building web, mobile and backend applications, APIs, databases, testing, version control, cloud deployment, Docker.'),
    ('Cybersecurity', 'Security analyst or engineer: protecting networks and systems, monitoring security alerts, incident response, penetration testing, vulnerability management, SIEM, firewalls.'),
    ('Digital Marketing', 'Digital marketer: social media, content, SEO, paid advertising campaigns, email marketing, brand growth, marketing analytics and campaign performance.'),
    ('Finance and Accounting', 'Accountant or financial analyst: bookkeeping, financial statements, budgeting, auditing, tax, payroll, financial reporting and analysis, Excel, ERP systems.')
ON CONFLICT (field_name) DO UPDATE SET description = EXCLUDED.description;


INSERT INTO users (name, email, role) VALUES
    ('Sara',  'sara@example.com',  'admin'),
    ('Omar',  'omar@example.com',  'recruiter'),
    ('Lina',  'lina@example.com',  'recruiter'),
    ('Nadia', 'nadia@example.com', 'recruiter')
ON CONFLICT (email) DO NOTHING;


INSERT INTO user_fields (user_id, field_id)
SELECT u.id, f.id
FROM users u
JOIN fields f ON (u.email, f.field_name) IN (
    ('omar@example.com',  'Cybersecurity'),
    ('lina@example.com',  'Data and AI'),
    ('lina@example.com',  'Software Engineering'),
    ('nadia@example.com', 'Digital Marketing'),
    ('nadia@example.com', 'Finance and Accounting')
)
ON CONFLICT DO NOTHING;