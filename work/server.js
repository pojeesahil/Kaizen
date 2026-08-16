const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

// Import routes and controller
const contactFormRoutes = require('./routes');
const contactFormController = require('./controller');

app.use(express.json());
app.use('/submit-contact-form', contactFormRoutes);
app.use('/submit-contact-form', contactFormController);

app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});