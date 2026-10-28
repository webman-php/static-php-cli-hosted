<?php
declare(strict_types=1);

function numeric(int $seed): int {
    $sum = 0;
    for ($i = 0; $i < 300; $i++) {
        $sum += (($i * 31 + $seed) % 997);
    }
    return $sum;
}
function floating(float $seed): float {
    for ($i = 0; $i < 150; $i++) {
        $seed = $seed * 0.995 + 0.125;
    }
    return $seed;
}
function maybeExit(bool $exit): int {
    if ($exit) {
        exit(37);
    }
    return numeric(3);
}
