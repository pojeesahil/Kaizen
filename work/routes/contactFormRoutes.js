const express = require('express');
const router = express.Router();

router.post('/submit-contact-form', (req, res) => {
    // Handle contact form submission logic here
    res.status(200).send('Contact form submitted successfully');
});

module.exports = router;