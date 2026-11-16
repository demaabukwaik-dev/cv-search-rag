INSERT INTO fields (field_name, code) VALUES
    ('Data and AI', 'DAI'),
    ('Software Engineering', 'SWE'),
    ('Cybersecurity', 'CYB'),
    ('Digital Marketing', 'MKT'),
    ('Finance and Accounting', 'FIN')  
ON CONFLICT (field_name) DO UPDATE SET code = EXCLUDED.code;


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