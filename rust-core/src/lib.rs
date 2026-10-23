//! Toroidal geometry. No RNG, network, filesystem, Python state or dependencies.
//!
//! ABI 1: callers own non-overlapping, aligned buffers of the advertised lengths.
//! Status 0 is success, 1 is an invalid size/pointer/length. No Rust allocation
//! crosses the ABI. All coordinate arithmetic uses i128 before returning i64.

const DIRECTIONS: [(i64, i64); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];

fn relative(origin: i64, target: i64, size: i64) -> i64 {
    let n = i128::from(size);
    ((i128::from(target) - i128::from(origin) + n / 2).rem_euclid(n) - n / 2) as i64
}

fn destination(x: i64, y: i64, dx: i64, dy: i64, size: i64) -> (i64, i64) {
    let n = i128::from(size);
    (((i128::from(x) + i128::from(dx)).rem_euclid(n)) as i64,
     ((i128::from(y) + i128::from(dy)).rem_euclid(n)) as i64)
}

#[unsafe(no_mangle)]
pub extern "C" fn ss_abi_version() -> u32 { 1 }

#[unsafe(no_mangle)]
pub extern "C" fn ss_in_range(x: i64, y: i64, tx: i64, ty: i64, size: i64, radius: i64) -> i32 {
    if size <= 0 { return -1; }
    i32::from(relative(x, tx, size).abs() <= radius && relative(y, ty, size).abs() <= radius)
}

/// # Safety
/// `output` must point to at least two writable, aligned i64 values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ss_relative(x: i64, y: i64, tx: i64, ty: i64,
                                     size: i64, output: *mut i64, output_len: usize) -> i32 {
    if size <= 0 || output.is_null() || output_len < 2 { return 1; }
    unsafe {
        output.write(relative(x, tx, size));
        output.add(1).write(relative(y, ty, size));
    }
    0
}

/// Emit (input index, dx, dy) triples, preserving the caller's order.
/// # Safety
/// `targets` is an aligned readable array of `target_len` i64s (x,y pairs).
/// `output` is a separate aligned writable array of `output_len` i64s.
/// `written` points to one writable usize and does not alias either buffer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ss_visible(x: i64, y: i64, size: i64, radius: i64,
                                    targets: *const i64, target_len: usize,
                                    output: *mut i64, output_len: usize, written: *mut usize) -> i32 {
    if size <= 0 || written.is_null() || target_len % 2 != 0
        || target_len > (isize::MAX as usize) / std::mem::size_of::<i64>() { return 1; }
    let count = target_len / 2;
    let Some(required) = count.checked_mul(3) else { return 1; };
    if output_len < required || required > (isize::MAX as usize) / std::mem::size_of::<i64>()
        || (count > 0 && (targets.is_null() || output.is_null())) { return 1; }
    unsafe { written.write(0); }
    // Avoid creating even a zero-length slice from a null pointer.
    if count == 0 { return 0; }
    let input = unsafe { std::slice::from_raw_parts(targets, target_len) };
    let mut found = 0;
    for (index, point) in input.chunks_exact(2).enumerate() {
        let dx = relative(x, point[0], size);
        let dy = relative(y, point[1], size);
        if dx.abs() <= radius && dy.abs() <= radius {
            unsafe {
                output.add(found * 3).write(index as i64);
                output.add(found * 3 + 1).write(dx);
                output.add(found * 3 + 2).write(dy);
            }
            found += 1;
        }
    }
    unsafe { written.write(found); }
    0
}

/// Unique reachable destinations in +x,-x,+y,-y order, optionally toward a delta.
/// # Safety
/// `output` holds at least 16 writable aligned i64s; `written` is separate.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ss_cardinal(x: i64, y: i64, size: i64,
                                     toward_x: i64, toward_y: i64, filter: u32,
                                     output: *mut i64, output_len: usize, written: *mut usize) -> i32 {
    if size <= 0 || output.is_null() || output_len < 16 || written.is_null() || filter > 1 { return 1; }
    let mut cells = [(0, 0); 4];
    let mut count = 0;
    for (dx, dy) in DIRECTIONS {
        if filter == 1 && i128::from(dx) * i128::from(toward_x) <= 0
            && i128::from(dy) * i128::from(toward_y) <= 0 { continue; }
        let target = destination(x, y, dx, dy, size);
        if cells[..count].contains(&target) { continue; }
        cells[count] = target;
        unsafe {
            output.add(count * 4).write(target.0);
            output.add(count * 4 + 1).write(target.1);
            output.add(count * 4 + 2).write(dx);
            output.add(count * 4 + 3).write(dy);
        }
        count += 1;
    }
    unsafe { written.write(count); }
    0
}

/// Return an unambiguous one-step delta. Status 2 means no unique match.
/// # Safety
/// `output` must point to two writable, aligned i64 values.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ss_absolute(x: i64, y: i64, tx: i64, ty: i64,
                                     size: i64, output: *mut i64, output_len: usize) -> i32 {
    if size <= 0 || output.is_null() || output_len < 2 { return 1; }
    if [x, y, tx, ty].iter().any(|v| *v < 0 || *v >= size) { return 2; }
    let mut matches = 0;
    let mut selected = (0, 0);
    for (dx, dy) in DIRECTIONS {
        if destination(x, y, dx, dy, size) == (tx, ty) {
            selected = (dx, dy);
            matches += 1;
        }
    }
    if matches != 1 { return 2; }
    unsafe { output.write(selected.0); output.add(1).write(selected.1); }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wrap_and_half_turn() {
        assert_eq!(relative(9, 0, 10), 1);
        assert_eq!(relative(0, 9, 10), -1);
        assert_eq!(relative(0, 5, 10), -5);
        assert_eq!(relative(0, 5, 11), 5);
        assert_eq!(relative(i64::MIN, i64::MAX, i64::MAX), 1);
        assert_eq!(relative(0, 0, 1), 0);
    }
    #[test]
    fn ffi_rejects_invalid_buffers_and_dimensions() {
        let mut out = [0_i64; 16];
        let mut written = 99;
        unsafe {
            assert_eq!(ss_relative(0, 0, 1, 1, 0, out.as_mut_ptr(), 2), 1);
            assert_eq!(ss_relative(0, 0, 1, 1, 2, std::ptr::null_mut(), 2), 1);
            assert_eq!(ss_visible(0, 0, 10, 1, std::ptr::null(), 0,
                                 std::ptr::null_mut(), 0, &mut written), 0);
            assert_eq!(written, 0);
            assert_eq!(ss_visible(0, 0, 10, 1, out.as_ptr(), 3,
                                 std::ptr::null_mut(), 0, &mut written), 1);
            assert_eq!(ss_cardinal(0, 0, 2, 0, 0, 0, out.as_mut_ptr(), 15, &mut written), 1);
            assert_eq!(ss_absolute(0, 0, 1, 0, 2, out.as_mut_ptr(), 2), 2);
            assert_eq!(ss_absolute(9, 0, 0, 0, 10, out.as_mut_ptr(), 2), 0);
            assert_eq!(&out[..2], &[1, 0]);
        }
    }
}
