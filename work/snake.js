// snake.js

const initialSnake = [{ x: 10, y: 10 }];
let direction = 'right';

function moveSnake(direction) {
  const head = { ...initialSnake[0] };
  switch (direction) {
    case 'up':
      head.y -= 1;
      break;
    case 'down':
      head.y += 1;
      break;
    case 'left':
      head.x -= 1;
      break;
    case 'right':
      head.x += 1;
      break;
    default:
      break;
  }
  initialSnake.unshift(head);
}

export { moveSnake, initialSnake };