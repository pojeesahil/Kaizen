const express = require('express');
const app = express();
const routes = require('./routes/routes.js');
const controller = require('./controller/controller.js');

app.use(express.json());

app.use('/', routes);
app.use('/', controller);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});