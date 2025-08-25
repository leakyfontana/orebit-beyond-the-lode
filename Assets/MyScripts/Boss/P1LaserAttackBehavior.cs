using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class P1LaserAttackBehavior : MonoBehaviour
{
	public GameObject player;
	public bool laser_is_going_clockwise;
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
		if(laser_is_going_clockwise)
			transform.Rotate(0, 0, (100 * Time.deltaTime));
		else
			transform.Rotate(0, 0, (-100 * Time.deltaTime));
    }
	
	public void startAttack(){
		Vector2 player_pos = player.transform.position;
		Vector2 laser_pos = transform.position;
		Vector2 vec = player_pos - laser_pos;
		float angleInDegrees = Mathf.Atan2(vec.y, vec.x) * Mathf.Rad2Deg;
		float offset = Random.Range(-1f, 1f);
		transform.rotation = Quaternion.Euler(0, 0, angleInDegrees - 90 + (offset * 90));
		if (offset <= 0)
			laser_is_going_clockwise = false;
		else
			laser_is_going_clockwise = true;
		print(offset);
		print(laser_is_going_clockwise);
	}
}
